"""服务状态监控插件 - 主入口点。"""

import asyncio
import os
import time
from typing import Optional, List

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter, MessageChain
from astrbot.api.star import Star, register

from .lib import ServiceRegistry, StatusChecker, format_status_change_message, CommandHandlers

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

        # 初始化模块
        self.status_checker = StatusChecker(self)  # 传入 self (Star 实例) 用于 KV 存储
        self.command_handlers = None  # 将在加载配置后初始化
    
    async def initialize(self):
        """初始化插件并开始监控。"""
        # 加载配置
        self._load_config()

        # 使用已加载的服务初始化命令处理器
        self.command_handlers = CommandHandlers(self.status_checker, self.services)

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

        logger.info(f"已加载 {len(self.services)} 个服务订阅")

    async def _notify_status_change(self, service_name: str, result: dict):
        """通知所有订阅的目标关于状态变更。"""
        if not self.notify_targets:
            logger.debug(f"[{service_name}] 状态变化但无通知目标")
            return

        # 格式化通知消息
        message_text = format_status_change_message(service_name, result)

        for target in self.notify_targets:
            try:
                message_chain = MessageChain().message(message_text)
                await self.context.send_message(target, message_chain)
                logger.info(f"[{service_name}] 已发送状态变化通知到: {target}")
            except Exception as e:
                logger.error(f"[{service_name}] 发送通知到 {target} 失败: {e}")

    async def _monitor_loop(self):
        """后台监控循环。"""
        import random

        error_backoff = 5  # 初始退避时间（秒）

        # 等待系统初始化
        await asyncio.sleep(5)

        while True:
            try:
                # 并发检查每个服务，错开延迟
                async def _check_and_notify(service_name, service):
                    """延迟检查单个服务并处理通知的辅助函数。"""
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

                        # 如果状态及变更，通知订阅者
                        if result and result.get('changed'):
                            logger.info(f"[{service_name}] 检测到状态变化，准备推送通知")
                            await self._notify_status_change(service_name, result)
                    except Exception as e:
                        logger.error(f"[{service_name}] 检查失败: {e}")

                tasks = [_check_and_notify(name, s) for name, s in self.services.items()]
                if tasks:
                    await asyncio.gather(*tasks)

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
        """Page: 获取所有已启用服务的实时状态。"""
        if not self.services:
            return json_response({
                "services": [],
                "summary": {"total": 0, "ok": 0, "problem": 0, "error": 0},
                "check_interval": self.check_interval,
                "checked_at": int(time.time()),
            })

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
            services.append(item)
            if item["status"] != "ok":
                summary["error"] += 1
            elif item["indicator"] in ("none", "operational", "rss_new"):
                summary["ok"] += 1
            else:
                summary["problem"] += 1

        return json_response({
            "services": services,
            "summary": summary,
            "check_interval": self.check_interval,
            "checked_at": int(time.time()),
        })

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
        self.command_handlers = CommandHandlers(self.status_checker, self.services)

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
