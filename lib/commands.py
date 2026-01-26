"""服务状态监控的命令处理器。"""

import asyncio
from typing import AsyncGenerator

from astrbot.api.event import AstrMessageEvent

from .formatters import format_status_list, format_test_result
from .status_checker import StatusChecker


class CommandHandlers:
    """服务状态监控命令的处理器。"""

    def __init__(self, status_checker: StatusChecker, services: dict):
        """初始化命令处理器。
        
        Args:
            status_checker: StatusChecker 实例
            services: 已启用服务的字典
        """
        self.status_checker = status_checker
        self.services = services

    async def handle_servicestatus(self, event: AstrMessageEvent) -> AsyncGenerator:
        """处理 /servicestatus 命令 - 显示所有服务状态。"""
        if not self.services:
            yield event.plain_result("未配置任何服务订阅")
            return

        # 并发获取所有服务的状态
        services_status = {}

        # 准备任务
        service_names = []
        tasks = []
        for service_name, service in self.services.items():
            service_names.append(service_name)
            tasks.append(self.status_checker.check_service(
                service_name,
                service.api_url,
                service.type,
                ignore_cache=False,
                update_db=False  # 手动检查状态时不更新数据库
            ))

        # 并行执行所有检查
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 收集结果
        for idx, result in enumerate(results):
            name = service_names[idx]
            if isinstance(result, Exception):
                # 应该在 check_service 内部处理，但以防万一
                continue
            services_status[name] = result

        # 格式化并返回
        response = format_status_list(services_status)
        yield event.plain_result(response)

    async def handle_servicetest(
            self,
            event: AstrMessageEvent,
            service_name: str
    ) -> AsyncGenerator:
        """处理 /servicetest 命令 - 测试服务监控。"""
        # 在已加载的服务中查找服务
        service = self.services.get(service_name)
        if not service:
            available = ', '.join(self.services.keys())
            yield event.plain_result(
                f"未配置或未启用的服务: {service_name}\n已配置服务: {available}"
            )
            return

        yield event.plain_result(f"正在测试获取 {service_name} ({service.api_url}) ...")

        # 忽略缓存检查状态
        try:
            result = await self.status_checker.check_service(
                service_name,
                service.api_url,
                service.type,
                ignore_cache=True,
                update_db=False  # 测试命令不应影响监控状态
            )

            response = format_test_result(service_name, result)
            yield event.plain_result(response)

        except Exception as e:
            yield event.plain_result(f"测试失败: {e}")
