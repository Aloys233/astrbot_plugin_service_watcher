"""Service Status Watcher Plugin - Main Entry Point."""

import asyncio
from typing import Optional, List
from astrbot.api.star import Star, register
from astrbot.api.event import AstrMessageEvent, filter, MessageChain
from astrbot.api import logger

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

        # Initialize modules
        self.status_checker = StatusChecker(self)  # Pass self (Star instance) for KV storage
        self.command_handlers = None  # Will be initialized after config load
    
    async def initialize(self):
        """Initialize plugin and start monitoring."""
        # Load configuration
        self._load_config()

        # Initialize command handlers with loaded services
        self.command_handlers = CommandHandlers(self.status_checker, self.services)

        # Start background monitoring
        self.monitoring_task = asyncio.create_task(self._monitor_loop())
        logger.info(f"服务监控插件已启动，监控间隔: {self.check_interval}秒，通知目标: {len(self.notify_targets)}个")

    def _load_config(self):
        """Load configuration from plugin config."""
        # Debug: print actual config received
        # Debug: check_interval and notify_targets count, avoid logging sensitive check urls
        logger.debug(
            f"加载配置: check_interval={self.config.get('check_interval')}, targets={len(self.config.get('notify_targets', []))}")

        # Load enabled services
        self.services = ServiceRegistry.load_from_config(self.config)

        # Load other settings
        self.check_interval = self.config.get("check_interval", 60)
        self.notify_targets = self.config.get("notify_targets", [])

        logger.info(f"已加载 {len(self.services)} 个服务订阅")

    async def _notify_status_change(self, service_name: str, result: dict):
        """Notify all subscribed targets about status change."""
        if not self.notify_targets:
            logger.debug(f"[{service_name}] 状态变化但无通知目标")
            return

        # Format notification message
        message_text = format_status_change_message(service_name, result)

        for target in self.notify_targets:
            try:
                message_chain = MessageChain().message(message_text)
                await self.context.send_message(target, message_chain)
                logger.info(f"[{service_name}] 已发送状态变化通知到: {target}")
            except Exception as e:
                logger.error(f"[{service_name}] 发送通知到 {target} 失败: {e}")

    async def _monitor_loop(self):
        """Background monitoring loop."""
        error_backoff = 5  # Initial backoff in seconds

        # Wait for system initialization
        await asyncio.sleep(5)

        while True:
            try:
                # Check all subscribed services
                for service_name, service in self.services.items():
                    result = await self.status_checker.check_service(
                        service_name,
                        service.api_url,
                        service.type
                    )

                    # If status changed, notify subscribers
                    if result and result.get('changed'):
                        logger.info(f"[{service_name}] 检测到状态变化，准备推送通知")
                        await self._notify_status_change(service_name, result)

                    # Avoid rate limiting
                    await asyncio.sleep(2)

                # Reset backoff on successful run
                error_backoff = 5

                # Wait for next check
                await asyncio.sleep(self.check_interval)
            except Exception as e:
                logger.error(f"监控循环出错: {e}")
                await asyncio.sleep(error_backoff)
                # Exponential backoff with max 60s
                error_backoff = min(error_backoff * 2, 60)

    # Command handlers

    @filter.command("servicestatus")
    async def cmd_status(self, event: AstrMessageEvent):
        """Query all service statuses."""
        async for result in self.command_handlers.handle_servicestatus(event):
            yield result

    @filter.command("servicetest")
    async def cmd_test(self, event: AstrMessageEvent, service_name: str):
        """Test service status monitoring."""
        async for result in self.command_handlers.handle_servicetest(event, service_name):
            yield result
    
    async def terminate(self):
        """Clean up resources."""
        if self.monitoring_task and not self.monitoring_task.done():
            self.monitoring_task.cancel()

        if self.status_checker:
            await self.status_checker.close()

        logger.info("服务监控插件已停止")
