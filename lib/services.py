"""用于服务状态监控的服务定义和注册表。"""

from dataclasses import dataclass
from typing import Dict

from astrbot.api import logger


@dataclass
class Service:
    """表示一个受监控的服务。"""
    name: str
    api_url: str
    type: str = "statuspage"  # statuspage 或 rss
    enabled: bool = True



class ServiceRegistry:
    """用于管理可用服务的注册表。"""

    @classmethod
    def load_from_json(cls, file_path: str) -> Dict[str, Service]:
        """从 JSON 文件加载服务定义。
        
        Args:
            file_path: services.json 文件的路径
            
        Returns:
            所有可用服务的字典
        """
        import json
        import os

        if not os.path.exists(file_path):
            return {}

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            services = {}
            for key, value in data.items():
                services[key] = Service(
                    name=value['name'],
                    api_url=value['api_url'],
                    type=value.get('type', 'statuspage'),
                    enabled=value.get('enabled', True)
                )
            return services
        except Exception as e:
            # 我们假设此处可能无法直接使用 logger，或者直接抛出/返回空
            # 但返回空总比文件损坏导致崩溃要好
            logger.error(f"Error loading services.json: {e}")
            return {}

    @classmethod
    def load_from_config(cls, config: dict, services_json_path: str) -> Dict[str, Service]:
        """基于配置开关加载已启用的服务。
        
        Args:
            config: 配置字典
            services_json_path: services.json 文件的路径
            
        Returns:
            映射服务名称到 Service 实例的字典
        """
        available_services = cls.load_from_json(services_json_path)
        services = {}

        # 扁平化配置以便于查找
        # 我们在根目录或 service_groups 内部的任何位置查找 'enable_<service_key>'
        enabled_keys = set()

        # 检查根级别键
        for k, v in config.items():
            if k.startswith("enable_") and v is True:
                enabled_keys.add(k)

        # 检查嵌套的 service_groups
        service_groups = config.get("service_groups", {})
        if isinstance(service_groups, dict):
            for group_data in service_groups.values():
                if isinstance(group_data, dict):
                    for k, v in group_data.items():
                        if k.startswith("enable_") and v is True:
                            enabled_keys.add(k)

        for key, service in available_services.items():
            config_key = f"enable_{key}"
            if config_key in enabled_keys:
                services[service.name] = service

        return services
