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


# Hardcoded service definitions - developers maintain this list
AVAILABLE_SERVICES = {
    "github": Service(
        name="GitHub",
        api_url="https://www.githubstatus.com/api/v2/summary.json",
        type="statuspage"
    ),
    "openai": Service(
        name="OpenAI",
        api_url="https://status.openai.com/api/v2/summary.json",
        type="statuspage"
    ),
    "cloudflare": Service(
        name="Cloudflare",
        api_url="https://www.cloudflarestatus.com/api/v2/summary.json",
        type="statuspage"
    ),
}


class ServiceRegistry:
    """Registry for managing available services."""

    @classmethod
    def load_from_config(cls, config: dict) -> Dict[str, Service]:
        """Load enabled services based on configuration toggles.
        
        Args:
            config: Configuration dictionary with 'enable_<service>' keys
            
        Returns:
            Dictionary mapping service name to Service instance
        """
        services = {}

        for key, service in AVAILABLE_SERVICES.items():
            config_key = f"enable_{key}"
            if config.get(config_key, False):
                services[service.name] = service

        return services
