"""服务状态监控插件 - 主入口点。"""

import asyncio
import os
from typing import Optional, List

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter, MessageChain
from astrbot.api.star import Star, register

from .lib import ServiceRegistry, StatusChecker, format_status_change_message, CommandHandlers


@register("service_watcher", "Aloys233", "监控互联网服务状态并推送更新", "0.0.1")
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

        # 加载其他设置
        self.check_interval = self.config.get("check_interval", 60)
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

        if self.status_checker:
            await self.status_checker.close()

        logger.info("服务监控插件已停止")
