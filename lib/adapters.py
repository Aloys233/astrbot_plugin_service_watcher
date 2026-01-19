from abc import ABC, abstractmethod
from typing import Dict, Optional, Any
from astrbot.api import logger


class BaseAdapter(ABC):
    """Abstract base class for service status adapters."""

    @abstractmethod
    async def fetch_status(self, client, service_name: str, api_url: str) -> Optional[Dict[str, Any]]:
        """
        Fetch and parse status from the service.
        
        Args:
            client: StatusAPIClient instance
            service_name: Name of the service
            api_url: URL to fetch status from
            
        Returns:
            Dict containing standardized status info or None if failed.
            Standard keys: 'indicator', 'description', 'id', 'raw_status', 'entry' (optional)
        """
        pass


class StatusPageAdapter(BaseAdapter):
    """Adapter for standard StatusPage.io JSON API."""

    STATUS_TRANSLATIONS = {
        'All Systems Operational': '所有系统运行正常',
        'Operational': '运行正常',
        'Major Service Outage': '严重服务中断',
        'Partial System Outage': '部分系统中断',
        'Minor Service Outage': '轻微服务中断',
        'Degraded Performance': '性能降级',
        'Under Maintenance': '正在维护',
        'Maintenance': '维护中',
        'Unknown': '未知'
    }

    async def fetch_status(self, client, service_name: str, api_url: str) -> Optional[Dict[str, Any]]:
        data = await client.fetch_json(service_name, api_url)
        if not data:
            return None

        status = data.get('status', {})
        indicator = status.get('indicator', 'none')
        raw_description = status.get('description', 'Unknown')

        # Translate description
        description = self.STATUS_TRANSLATIONS.get(raw_description, raw_description)

        return {
            'indicator': indicator,
            'description': description,
            'raw_status': status,
            'id': f"{indicator}|{description}"
        }


class RSSAdapter(BaseAdapter):
    """Adapter for RSS/Atom feeds."""

    async def fetch_status(self, client, service_name: str, api_url: str) -> Optional[Dict[str, Any]]:
        data = await client.fetch_rss(service_name, api_url)
        if not data:
            return None

        entries = data.get('entries', [])
        if not entries:
            return {
                'indicator': 'none',
                'description': '暂无更新',
                'id': 'empty',
                'raw_status': data
            }

        latest = entries[0]
        # Use entry ID or published date as unique identifier
        entry_id = latest.get('id') or latest.get('published') or latest.get('link')

        return {
            'indicator': 'rss_new',
            'description': latest.get('title', '新动态'),
            'id': entry_id,
            'entry': latest,
            'raw_status': None  # RSS data is too large/complex to store as raw status usually
        }


class AliyunAdapter(BaseAdapter):
    """Adapter for Alibaba Cloud status API."""

    async def fetch_status(self, client, service_name: str, api_url: str) -> Optional[Dict[str, Any]]:
        data = await client.fetch_json(service_name, api_url)
        if not data:
            return None

        # Alibaba Cloud returns {"data": [], "total": 0, "success": true, ...}
        # data is a list of events in progress
        events = data.get('data', [])

        if not events:
            return {
                'indicator': 'none',
                'description': '所有系统运行正常',
                'id': 'empty_list',
                'raw_status': data
            }

        # If there are events, take the first one or valid summary
        # We'll use the list of event IDs as the unique ID for the status
        event_ids = ",".join(sorted(str(e.get('id', 'unknown')) for e in events))

        return {
            'indicator': 'minor',  # Assume minor if there are events
            'description': f"{len(events)} 个活跃事件",
            'id': f"events_{event_ids}",
            'raw_status': data
        }
