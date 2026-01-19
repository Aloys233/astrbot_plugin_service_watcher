"""Command handlers for service status monitoring."""

from astrbot.api.event import AstrMessageEvent
import asyncio
from typing import AsyncGenerator
from .services import ServiceRegistry
from .status_checker import StatusChecker
from .formatters import format_status_list, format_test_result


class CommandHandlers:
    """Handlers for service status monitoring commands."""

    def __init__(self, status_checker: StatusChecker, services: dict):
        """Initialize command handlers.
        
        Args:
            status_checker: StatusChecker instance
            services: Dictionary of enabled services
        """
        self.status_checker = status_checker
        self.services = services

    async def handle_servicestatus(self, event: AstrMessageEvent) -> AsyncGenerator:
        """Handle /servicestatus command - show all service statuses."""
        if not self.services:
            yield event.plain_result("未配置任何服务订阅")
            return

        # Fetch status for all services
        # Fetch status for all services concurrently
        services_status = {}

        # Prepare tasks
        service_names = []
        tasks = []
        for service_name, service in self.services.items():
            service_names.append(service_name)
            tasks.append(self.status_checker.check_service(
                service_name,
                service.api_url,
                service.type,
                ignore_cache=False,
                update_db=False  # Don't update DB on manual status check
            ))

        # Execute all checks in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Collect results
        for idx, result in enumerate(results):
            name = service_names[idx]
            if isinstance(result, Exception):
                # Should be handled inside check_service, but just in case
                continue
            services_status[name] = result

        # Format and return
        response = format_status_list(services_status)
        yield event.plain_result(response)

    async def handle_servicetest(
            self,
            event: AstrMessageEvent,
            service_name: str
    ) -> AsyncGenerator:
        """Handle /servicetest command - test service monitoring."""
        # Find service in loaded services
        service = self.services.get(service_name)
        if not service:
            available = ', '.join(self.services.keys())
            yield event.plain_result(
                f"未配置或未启用的服务: {service_name}\n已配置服务: {available}"
            )
            return

        yield event.plain_result(f"正在测试获取 {service_name} ({service.api_url}) ...")

        # Check status with cache ignored
        try:
            result = await self.status_checker.check_service(
                service_name,
                service.api_url,
                service.type,
                ignore_cache=True,
                update_db=False  # Test command should not affect monitoring state
            )

            response = format_test_result(service_name, result)
            yield event.plain_result(response)

        except Exception as e:
            yield event.plain_result(f"测试失败: {e}")
