"""服务状态监控插件 - 主入口点。"""

import asyncio
import os
import time
from datetime import date, datetime, timezone
from typing import Optional, List, Dict

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter, MessageChain
from astrbot.api.star import Star, register

from .lib import (
    ServiceRegistry,
    StatusChecker,
    format_status_change_message,
    format_status_list,
    CommandHandlers,
    Translator,
    diff_statuspage,
    diff_aliyun,
    normalize_policy,
    should_notify,
)
from .lib import subscriptions
from .lib import uptime
from .lib.text import format_time

PLUGIN_NAME = "astrbot_plugin_service_watcher"

try:  # 插件 Pages 的 Web API 需要较新的 AstrBot 版本
    from astrbot.api.web import error_response, json_response, request
    _WEB_API_AVAILABLE = True
except ImportError:
    _WEB_API_AVAILABLE = False


@register("service_watcher", "Aloys233", "监控互联网服务状态并推送更新", "0.4.0")
class ServiceWatcher(Star):
    """服务状态监控插件，通过 JSON API 监控互联网服务状态"""

    def __init__(self, context, config) -> None:
        super().__init__(context)
        self.config = config  # 插件配置通过参数传入
        self.services = {}
        self.check_interval: int = 60
        self.notify_targets: List[str] = []  # 订阅通知的会话列表
        self.monitoring_task: Optional[asyncio.Task] = None
        self.translator: Optional[Translator] = None  # AI 翻译器（可选功能）
        self._status_cache: Optional[dict] = None  # /status API 的 TTL 缓存 {data, ts}

        # 初始化模块
        self.status_checker = StatusChecker(self)  # 传入 self (Star 实例) 用于 KV 存储
        self.command_handlers = None  # 将在加载配置后初始化
    
    async def initialize(self):
        """初始化插件并开始监控。"""
        # 加载配置
        self._load_config()

        # 使用已加载的服务初始化命令处理器
        self.command_handlers = CommandHandlers(self.status_checker, self.services, self.translator)

        # 注册插件 Pages 的后端 Web API
        self._register_pages_api()

        # 开始后台监控
        self.monitoring_task = asyncio.create_task(self._monitor_loop())
        logger.info(f"服务监控插件已启动，监控间隔: {self.check_interval}秒，通知目标: {len(self.notify_targets)}个")

    def _load_config(self):
        """从插件配置加载配置。"""
        # 调试：打印接收到的实际配置
        # 调试：check_interval 和 notify_targets 数量，避免记录敏感的检查 URL
        logger.debug(
            f"加载配置: check_interval={self.config.get('check_interval')}, targets={len(self.config.get('notify_targets', []))}")

        # 加载已启用的服务
        services_path = os.path.join(os.path.dirname(__file__), "services.json")
        self.services = ServiceRegistry.load_from_config(self.config, services_path)

        # 加载其他设置（间隔过短会频繁请求上游 API，限制最小 10 秒）
        try:
            check_interval = int(self.config.get("check_interval", 60))
        except (TypeError, ValueError):
            check_interval = 60
        self.check_interval = max(10, check_interval)
        self.notify_targets = self.config.get("notify_targets", [])
        self._status_cache = None  # 服务列表变化，使 /status 缓存失效

        # AI 翻译（可选）：仅在开关打开且选择了提供商时生效
        if self.config.get("enable_translation", False):
            self.translator = Translator(self.context, self.config.get("translation_provider", ""))
        else:
            self.translator = None

        # 推送灵敏度（low/medium/high）与提醒、摘要设置
        self.notify_policy = normalize_policy(self.config.get("notify_policy", "high"))
        try:
            self.maintenance_remind_minutes = max(
                0, int(self.config.get("maintenance_remind_minutes", 60)))
        except (TypeError, ValueError):
            self.maintenance_remind_minutes = 60
        self.daily_summary_enabled = bool(self.config.get("daily_summary_enabled", False))
        self.daily_summary_time = str(self.config.get("daily_summary_time", "09:00")).strip()

        logger.info(f"已加载 {len(self.services)} 个服务订阅")

    @staticmethod
    def _diff_lines_for(result: dict) -> Optional[List[str]]:
        """计算快照差异行（用于推送灵敏度判定，需在翻译前调用）。"""
        service_type = result.get('type')
        previous = result.get('previous')
        if service_type not in ('statuspage', 'aliyun') or not isinstance(previous, dict):
            return None
        info = result.get('info') or {}
        details = info.get('details') if isinstance(info, dict) else None
        if service_type == 'statuspage':
            return diff_statuspage(previous, details)
        return diff_aliyun(previous, details)

    async def _notify_status_change(self, service_name: str, service, result: dict):
        """通知所有订阅的目标关于状态变更。"""
        # 推送灵敏度判定（在翻译前进行，避免无谓的模型调用）
        prev_indicator = None
        previous = result.get('previous')
        if isinstance(previous, dict):
            prev_indicator = previous.get('indicator')
        diff_lines = self._diff_lines_for(result)
        if not should_notify(self.notify_policy, prev_indicator,
                             result.get('indicator'), diff_lines, result.get('type', '')):
            logger.debug(f"[{service_name}] 状态变化未达到推送灵敏度 ({self.notify_policy})，跳过推送")
            return

        # 通知目标 = 全局 notify_targets ∪ 订阅了该服务的会话（去重）
        targets = await self._union_targets(service.key)

        if not targets:
            logger.debug(f"[{service_name}] 状态变化但无通知目标")
            return

        # 可选：AI 翻译通知中的英文内容（失败时保留原文）
        if self.translator:
            try:
                await self.translator.translate_result(result)
            except Exception as e:
                logger.warning(f"[{service_name}] 翻译失败，使用原文通知: {e}")

        # 格式化通知消息
        message_text = format_status_change_message(service_name, result)

        await self._send_to_targets(service_name, message_text, targets)

    async def _union_targets(self, service_key: Optional[str] = None) -> List[str]:
        """全局通知目标与（可选的）指定服务订阅会话的并集，去重。"""
        targets = list(self.notify_targets)
        if service_key:
            try:
                for target in await subscriptions.get_targets(self.status_checker.star, service_key):
                    if target not in targets:
                        targets.append(target)
            except Exception as e:
                logger.warning(f"读取服务 {service_key} 的订阅列表失败: {e}")
        return targets

    async def _send_to_targets(self, service_name: str, message_text: str, targets: List[str]):
        """向目标会话列表发送文本消息。"""
        for target in targets:
            try:
                message_chain = MessageChain().message(message_text)
                await self.context.send_message(target, message_chain)
                logger.info(f"[{service_name}] 已发送通知到: {target}")
            except Exception as e:
                logger.error(f"[{service_name}] 发送通知到 {target} 失败: {e}")

    @staticmethod
    def _parse_iso_time(value) -> Optional[datetime]:
        """解析 ISO 时间字符串为 aware datetime；失败返回 None。"""
        text = str(value or '').strip()
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            return None

    async def _check_maintenance_reminders(self, services: dict, results: list):
        """检查即将开始的计划维护，在窗口期内提醒一次。"""
        window = self.maintenance_remind_minutes
        if window <= 0:
            return

        try:
            reminded: List[str] = await self.status_checker.star.get_kv_data(
                "service_watcher_maint_reminded", []) or []
            if not isinstance(reminded, list):
                reminded = []

            now = datetime.now(timezone.utc)
            fresh = False

            for (name, service), result in zip(services.items(), results):
                if not result or service.type != 'statuspage':
                    continue
                info = result.get('info') or {}
                details = info.get('details') if isinstance(info, dict) else {}
                for maintenance in details.get('maintenances', []) or []:
                    if not isinstance(maintenance, dict):
                        continue
                    scheduled = self._parse_iso_time(maintenance.get('scheduled_for'))
                    if scheduled is None:
                        continue
                    minutes_left = (scheduled - now).total_seconds() / 60
                    if not (0 < minutes_left <= window):
                        continue
                    marker = f"{service.key}:{maintenance.get('id')}"
                    if marker in reminded:
                        continue
                    reminded.append(marker)
                    fresh = True

                    lines = [
                        f"🔧 [{name}] 计划维护提醒",
                        f"维护: {maintenance.get('title', '计划维护')}",
                        f"状态: {maintenance.get('status_cn') or maintenance.get('status', 'scheduled')}",
                        f"计划时间: {format_time(maintenance.get('scheduled_for'))}",
                        f"预计 {int(minutes_left)} 分钟后开始",
                    ]
                    targets = await self._union_targets(service.key)
                    await self._send_to_targets(name, "\n".join(lines), targets)

            if fresh:
                await self.status_checker.star.put_kv_data("service_watcher_maint_reminded", reminded)
        except Exception as e:
            logger.warning(f"维护提醒检查失败: {e}")

    async def _maybe_send_daily_summary(self):
        """在配置的每日时间点推送一次全量状态摘要。"""
        if not self.daily_summary_enabled:
            return

        try:
            today = date.today().isoformat()
            last = await self.status_checker.star.get_kv_data("service_watcher_last_summary_date", None)
            if last == today:
                return

            now = datetime.now()
            try:
                hh, mm = self.daily_summary_time.split(':')
                target_minutes = int(hh) * 60 + int(mm)
            except (ValueError, AttributeError):
                target_minutes = 9 * 60
            if now.hour * 60 + now.minute < target_minutes:
                return

            # 全量检查一次（不更新 KV，不影响推送判定）
            async def _check(name, service):
                try:
                    return await self.status_checker.check_service(
                        name, service.api_url, service.type,
                        ignore_cache=False, update_db=False)
                except Exception:
                    return None

            names = list(self.services.keys())
            results = await asyncio.gather(*(_check(n, self.services[n]) for n in names))
            services_status = dict(zip(names, results))
            message_text = "📊 每日状态摘要\n\n" + format_status_list(services_status)

            targets = list(self.notify_targets)
            for target in await subscriptions.get_all_targets(self.status_checker.star):
                if target not in targets:
                    targets.append(target)
            if targets:
                await self._send_to_targets("每日摘要", message_text, targets)

            await self.status_checker.star.put_kv_data("service_watcher_last_summary_date", today)
        except Exception as e:
            logger.warning(f"每日摘要发送失败: {e}")

    async def _monitor_loop(self):
        """后台监控循环。"""
        import random

        error_backoff = 5  # 初始退避时间（秒）
        failure_counts: Dict[str, int] = {}  # 各服务连续失败次数
        skip_rounds: Dict[str, int] = {}  # 连续失败后的跳过轮数

        # 等待系统初始化
        await asyncio.sleep(5)

        while True:
            try:
                # 并发检查每个服务，错开延迟
                async def _check_and_notify(service_name, service):
                    """延迟检查单个服务并处理通知的辅助函数。"""
                    # 连续失败退避：跳过本轮检查
                    if skip_rounds.get(service_name, 0) > 0:
                        skip_rounds[service_name] -= 1
                        logger.debug(f"[{service_name}] 连续失败退避中，本轮跳过")
                        return

                    try:
                        # 添加微小的随机延迟，使请求在 5 秒窗口内错开
                        delay = random.uniform(0, 5)
                        await asyncio.sleep(delay)

                        # 检查服务状态
                        result = await self.status_checker.check_service(
                            service_name,
                            service.api_url,
                            service.type
                        )

                        # 记录可用性统计与连续失败计数
                        check_ok = bool(result) and not result.get('error')
                        if check_ok:
                            failure_counts.pop(service_name, None)
                        else:
                            failure_counts[service_name] = failure_counts.get(service_name, 0) + 1
                            if failure_counts[service_name] >= 3:
                                # 连续 3 次失败后跳过接下来 2 轮，避免高频轰炸故障源
                                skip_rounds[service_name] = 2
                                failure_counts[service_name] = 0
                                logger.warning(
                                    f"[{service_name}] 连续检查失败，退避 2 轮后再试")

                        await uptime.record(
                            self.status_checker.star, service.key,
                            result.get('indicator', '') if result else '', check_ok)

                        # 如果状态及变更，通知订阅者
                        if result and result.get('changed'):
                            logger.info(f"[{service_name}] 检测到状态变化，准备推送通知")
                            await self._notify_status_change(service_name, service, result)

                        return result
                    except Exception as e:
                        logger.error(f"[{service_name}] 检查失败: {e}")
                        return None

                tasks = [_check_and_notify(name, s) for name, s in self.services.items()]
                results = await asyncio.gather(*tasks) if tasks else []

                # 维护窗口提醒与每日摘要（每轮检查后执行一次）
                await self._check_maintenance_reminders(self.services, results)
                await self._maybe_send_daily_summary()

                # 成功运行后重置退避
                error_backoff = 5

                # 等待下一个检查间隔
                await asyncio.sleep(self.check_interval)
            except Exception as e:
                logger.error(f"监控循环出错: {e}")
                await asyncio.sleep(error_backoff)
                # 指数退避，最大 60 秒
                error_backoff = min(error_backoff * 2, 60)

    # 插件 Pages 后端 API

    def _register_pages_api(self):
        """注册插件 Pages 页面使用的后端 Web API。"""
        if not _WEB_API_AVAILABLE or not hasattr(self.context, "register_web_api"):
            logger.warning("当前 AstrBot 版本不支持插件 Pages Web API，已跳过注册")
            return

        prefix = f"/{PLUGIN_NAME}"
        self.context.register_web_api(f"{prefix}/status", self.api_status, ["GET"], "获取已启用服务的实时状态")
        self.context.register_web_api(f"{prefix}/services", self.api_services, ["GET"], "获取服务列表与插件配置")
        self.context.register_web_api(f"{prefix}/config", self.api_save_config, ["POST"], "保存插件配置")

    @staticmethod
    def _service_item(name: str, service, result: Optional[dict]) -> dict:
        """将 check_service 的结果转换为 Page 需要的 JSON 结构。"""
        item = {
            "key": service.key,
            "name": name,
            "type": service.type,
            "status": "error",
            "error": "获取失败",
        }
        if result is None:
            return item
        if isinstance(result, dict) and result.get("error"):
            item["error"] = str(result.get("error"))
            return item

        info = result.get("info") or {}
        details = info.get("details", {}) if isinstance(info, dict) else {}
        item.pop("error", None)
        item.update({
            "status": "ok",
            "indicator": result.get("indicator", "none"),
            "description": result.get("description", ""),
        })

        if result.get("type") == "statuspage":
            item["incidents"] = details.get("incident_count", 0)
            item["maintenances"] = details.get("maintenance_count", 0)
            incidents = details.get("incidents", [])
            maintenances = details.get("maintenances", [])
            if isinstance(incidents, list):
                item["incident_items"] = incidents[:20]
            if isinstance(maintenances, list):
                item["maintenance_items"] = maintenances[:20]
            if details.get("page_url"):
                item["page_url"] = details.get("page_url")
        elif result.get("type") == "probe":
            item["http_status"] = details.get("status_code")
            item["latency_ms"] = details.get("latency_ms")
            item["target"] = details.get("target")
            if details.get("error"):
                item["error"] = details.get("error")
        elif result.get("type") == "aliyun":
            item["events"] = details.get("event_count", 0)
            events = details.get("events", [])
            if isinstance(events, list):
                item["event_items"] = events[:20]
        elif result.get("type") == "rss":
            if isinstance(details, dict):
                item["entry"] = {
                    "title": details.get("title"),
                    "published": details.get("published"),
                    "author": details.get("author"),
                    "summary": details.get("summary"),
                }
                if details.get("link"):
                    item["link"] = details.get("link")
        return item

    async def api_status(self):
        """Page: 获取所有已启用服务的实时状态（带 30 秒 TTL 缓存）。"""
        now = time.time()
        if self._status_cache and now - self._status_cache['ts'] < 30:
            return json_response(self._status_cache['data'])

        if not self.services:
            payload = {
                "services": [],
                "summary": {"total": 0, "ok": 0, "problem": 0, "error": 0},
                "check_interval": self.check_interval,
                "checked_at": int(time.time()),
            }
            self._status_cache = {'data': payload, 'ts': now}
            return json_response(payload)

        async def _check(name, service):
            try:
                return await self.status_checker.check_service(
                    name, service.api_url, service.type,
                    ignore_cache=False, update_db=False,
                )
            except Exception as e:
                return {"error": str(e)}

        names = list(self.services.keys())
        results = await asyncio.gather(*(_check(n, self.services[n]) for n in names))

        services = []
        summary = {"total": len(names), "ok": 0, "problem": 0, "error": 0}
        for name, result in zip(names, results):
            item = self._service_item(name, self.services[name], result)
            service = self.services[name]
            try:
                item["uptime_7d"] = (await uptime.summary(self.status_checker.star, service.key, 7))["ratio"]
                item["uptime_30d"] = (await uptime.summary(self.status_checker.star, service.key, 30))["ratio"]
            except Exception:
                pass
            services.append(item)
            if item["status"] != "ok":
                summary["error"] += 1
            elif item["indicator"] in ("none", "operational", "rss_new"):
                summary["ok"] += 1
            else:
                summary["problem"] += 1

        payload = {
            "services": services,
            "summary": summary,
            "check_interval": self.check_interval,
            "checked_at": int(time.time()),
        }
        self._status_cache = {'data': payload, 'ts': now}
        return json_response(payload)

    async def api_services(self):
        """Page: 获取所有可用服务、分组及当前启用状态。"""
        services_path = os.path.join(os.path.dirname(__file__), "services.json")
        available = ServiceRegistry.load_from_json(services_path)
        enabled_keys = {s.key for s in self.services.values()}

        groups = []
        service_groups = self.config.get("service_groups", {})
        if isinstance(service_groups, dict):
            for group_id, group_data in service_groups.items():
                if not isinstance(group_data, dict):
                    continue
                keys = [k[len("enable_"):] for k in group_data
                        if isinstance(k, str) and k.startswith("enable_")]
                groups.append({
                    "id": group_id,
                    "description": str(group_data.get("description", group_id)),
                    "keys": keys,
                })

        items = []
        for key, service in available.items():
            items.append({
                "key": key,
                "name": service.name,
                "type": service.type,
                "enabled": key in enabled_keys,
                "available": service.enabled,
            })

        return json_response({
            "groups": groups,
            "services": items,
            "check_interval": self.check_interval,
            "notify_targets": self.notify_targets,
        })

    async def api_save_config(self):
        """Page: 保存插件配置（服务开关、检查间隔、通知目标）。"""
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("请求体必须是 JSON 对象", status_code=400)

        enabled = payload.get("enabled")
        if enabled is not None and not isinstance(enabled, dict):
            return error_response("enabled 必须是对象", status_code=400)

        interval = payload.get("check_interval")
        if interval is not None:
            if isinstance(interval, bool) or not isinstance(interval, int):
                return error_response("check_interval 必须是整数", status_code=400)
            interval = max(10, min(interval, 86400))

        targets = payload.get("notify_targets")
        if targets is not None:
            if not isinstance(targets, list) or not all(isinstance(t, str) for t in targets):
                return error_response("notify_targets 必须是字符串列表", status_code=400)

        if enabled is not None:
            service_groups = self.config.get("service_groups", {})
            if isinstance(service_groups, dict):
                for group_data in service_groups.values():
                    if not isinstance(group_data, dict):
                        continue
                    for config_key in list(group_data.keys()):
                        if isinstance(config_key, str) and config_key.startswith("enable_"):
                            service_key = config_key[len("enable_"):]
                            if service_key in enabled:
                                group_data[config_key] = bool(enabled[service_key])

        if interval is not None:
            self.config["check_interval"] = interval
        if targets is not None:
            self.config["notify_targets"] = targets

        save = getattr(self.config, "save_config", None)
        if callable(save):
            save()

        # 重新加载配置，并同步命令处理器持有的服务列表引用
        self._load_config()
        self.command_handlers = CommandHandlers(self.status_checker, self.services, self.translator)

        return json_response({
            "saved": True,
            "check_interval": self.check_interval,
            "enabled_count": len(self.services),
        })

    # 命令处理器

    @filter.command("servicestatus")
    async def cmd_status(self, event: AstrMessageEvent):
        """查询所有服务状态"""
        async for result in self.command_handlers.handle_servicestatus(event):
            yield result

    @filter.command("servicetest")
    async def cmd_test(self, event: AstrMessageEvent, service_name: str):
        """测试服务状态监控"""
        async for result in self.command_handlers.handle_servicetest(event, service_name):
            yield result

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("servicewatch")
    async def cmd_servicewatch(self, event: AstrMessageEvent, action: str = "", service_name: str = ""):
        """管理当前会话的服务状态订阅（仅管理员）"""
        umo = event.unified_msg_origin
        star = self.status_checker.star

        action = (action or "").strip()
        service_name = (service_name or "").strip()

        # 无参数 / list：显示当前会话订阅列表
        if action in ("", "list", "列表", "状态"):
            subscribed = await subscriptions.list_for(star, umo)
            names = [self.services[k].name for k in subscribed if k in self.services] or []
            lines = ["📡 当前会话的服务订阅", ""]
            if names:
                lines.extend(f"• {name}" for name in names)
            else:
                lines.append("（暂无订阅）")
            lines.append("")
            lines.append("用法：")
            lines.append("• /servicewatch <服务名|all> 订阅")
            lines.append("• /servicewatch off <服务名|all> 退订")
            lines.append(f"已配置服务: {', '.join(s.name for s in self.services.values()) or '无'}")
            yield event.plain_result("\n".join(lines))
            return

        # 退订
        if action in ("off", "取消", "退订"):
            if not service_name:
                yield event.plain_result("用法: /servicewatch off <服务名|all>")
                return
            if service_name.lower() == "all":
                subscribed = await subscriptions.list_for(star, umo)
                if not subscribed:
                    yield event.plain_result("当前会话没有任何订阅")
                    return
                for key in subscribed:
                    await subscriptions.unsubscribe(star, key, umo)
                yield event.plain_result(f"已退订全部 {len(subscribed)} 个服务")
                return
            service = self.command_handlers._find_service(service_name)
            if not service:
                yield event.plain_result(f"未配置或未启用的服务: {service_name}")
                return
            if await subscriptions.unsubscribe(star, service.key, umo):
                yield event.plain_result(f"已退订: {service.name}")
            else:
                yield event.plain_result(f"当前会话未订阅: {service.name}")
            return

        # 订阅
        if action.lower() == "all":
            count = 0
            for service in self.services.values():
                if await subscriptions.subscribe(star, service.key, umo):
                    count += 1
            yield event.plain_result(f"已订阅全部服务（新增 {count} 个，其余已订阅）")
            return

        service = self.command_handlers._find_service(action)
        if not service:
            available = ', '.join(s.name for s in self.services.values())
            yield event.plain_result(f"未配置或未启用的服务: {action}\n已配置服务: {available}")
            return
        if await subscriptions.subscribe(star, service.key, umo):
            yield event.plain_result(f"已订阅: {service.name}\n该服务状态变化时将通知当前会话")
        else:
            yield event.plain_result(f"当前会话已订阅: {service.name}")
    
    async def terminate(self):
        """清理资源。"""
        if self.monitoring_task and not self.monitoring_task.done():
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass

        await self.status_checker.close()

        logger.info("服务监控插件已停止")
