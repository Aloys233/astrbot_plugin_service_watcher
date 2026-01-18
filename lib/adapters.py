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

    async def fetch_status(self, client, service_name: str, api_url: str) -> Optional[Dict[str, Any]]:
        data = await client.fetch_json(service_name, api_url)
        if not data:
            return None

        status = data.get('status', {})
        indicator = status.get('indicator', 'none')
        description = status.get('description', 'Unknown')

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
                'description': 'No updates',
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
                'description': 'All systems operational',
                'id': 'empty_list',
                'raw_status': data
            }

        # If there are events, take the first one or valid summary
        # We'll use the list of event IDs as the unique ID for the status
        event_ids = ",".join(sorted(str(e.get('id', 'unknown')) for e in events))

        return {
            'indicator': 'minor',  # Assume minor if there are events
            'description': f"{len(events)} active events",
            'id': f"events_{event_ids}",
            'raw_status': data
        }
