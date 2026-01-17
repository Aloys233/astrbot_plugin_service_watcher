"""Service definitions and registry for service status monitoring."""

from dataclasses import dataclass
from typing import Dict


@dataclass
class Service:
    """Represents a monitored service."""
    name: str
    api_url: str
    type: str = "statuspage"  # statuspage or rss
    enabled: bool = True



class ServiceRegistry:
    """Registry for managing available services."""

    @classmethod
    def load_from_json(cls, file_path: str) -> Dict[str, Service]:
        """Load service definitions from a JSON file.
        
        Args:
            file_path: Path to the services.json file
            
        Returns:
            Dictionary of all available services
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
            # We assume logger might not be available here directly or we just raise/return empty
            # But better to return empty than crash if file is bad
            print(f"Error loading services.json: {e}")
            return {}

    @classmethod
    def load_from_config(cls, config: dict, services_json_path: str) -> Dict[str, Service]:
        """Load enabled services based on configuration toggles.
        
        Args:
            config: Configuration dictionary
            services_json_path: Path to the services.json file
            
        Returns:
            Dictionary mapping service name to Service instance
        """
        available_services = cls.load_from_json(services_json_path)
        services = {}

        # Flatten the configuration for easier lookup
        # We look for 'enable_<service_key>' in root or anywhere inside service_groups
        enabled_keys = set()

        # Check root level keys
        for k, v in config.items():
            if k.startswith("enable_") and v is True:
                enabled_keys.add(k)

        # Check nested service_groups
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
