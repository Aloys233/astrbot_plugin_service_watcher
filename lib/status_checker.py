import asyncio
from typing import Optional, Dict

import aiohttp
import feedparser
from astrbot.api import logger


class StatusAPIClient:
    """HTTP client for fetching service status from various sources."""

    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create client session."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(trust_env=True)
        return self.session

    async def close(self):
        """Close client session."""
        if self.session and not self.session.closed:
            await self.session.close()

    async def fetch_json(self, service_name: str, api_url: str) -> Optional[dict]:
        """Fetch JSON data from API."""
        try:
            session = await self._get_session()
            async with session.get(api_url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    logger.error(f"[{service_name}] API请求失败: HTTP {response.status}")
                    return None
                return await response.json()
        except Exception as e:
            import traceback
            logger.error(f"[{service_name}] 获取 JSON 状态失败: {repr(e)}")
            logger.debug(traceback.format_exc())
            return None

    async def fetch_rss(self, service_name: str, rss_url: str) -> Optional[dict]:
        """Fetch and parse RSS feed."""
        try:
            session = await self._get_session()
            async with session.get(rss_url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    logger.error(f"[{service_name}] RSS请求失败: HTTP {response.status}")
                    return None
                content = await response.read()

                # Parse in executor to avoid blocking event loop
                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(None, feedparser.parse, content)
        except Exception as e:
            import traceback
            logger.error(f"[{service_name}] 获取 RSS 状态失败: {repr(e)}")
            logger.debug(traceback.format_exc())
            return None


from .adapters import StatusPageAdapter, RSSAdapter, AliyunAdapter

class StatusChecker:
    """Check service status and detect changes for multiple types."""

    # Status emoji mapping
    STATUS_EMOJI = {
        'none': '✅',
        'operational': '✅',
        'minor': '⚠️',
        'major': '❌',
        'critical': '🚨',
        'maintenance': '🔧',
        'degraded_performance': '⚠️',
        'partial_outage': '❌',
        'under_maintenance': '🔧',
        'rss_new': '📝'
    }

    def __init__(self, star):
        """Initialize status checker with Star instance for KV storage.
        
        Args:
            star: Star instance that provides get_kv_data/put_kv_data methods
        """
        self.star = star
        self.api_client = StatusAPIClient()
        self.adapters = {
            'statuspage': StatusPageAdapter(),
            'rss': RSSAdapter(),
            'aliyun': AliyunAdapter()
        }

    async def close(self):
        """Cleanup resources."""
        await self.api_client.close()

    @staticmethod
    def get_emoji(indicator: str) -> str:
        """Get emoji for status indicator."""
        return StatusChecker.STATUS_EMOJI.get(indicator, '📊')

    async def check_service(
            self,
            service_name: str,
            api_url: str,
            service_type: str = "statuspage",
            ignore_cache: bool = False,
            update_db: bool = True
    ) -> Optional[Dict[str, any]]:
        """Check service status and detect changes.
        
        Args:
            service_name: Name of the service
            api_url: URL to fetch status from
            service_type: Type of service (statuspage/rss/aliyun)
            ignore_cache: If True, ignore last_id comparison for changed flag
            update_db: If True, update KV storage with new status ID
        """
        adapter = self.adapters.get(service_type)
        if not adapter:
            logger.error(f"[{service_name}] Unknown service type: {service_type}")
            return None

        status_info = await adapter.fetch_status(self.api_client, service_name, api_url)

        if not status_info:
            return None

        current_id = status_info['id']

        # Check KV storage for last status (using Star's async KV methods)
        kv_key = f"service_watcher_{service_name}_last_id"
        last_id = await self.star.get_kv_data(kv_key, None)

        # Debug: log the state
        logger.debug(f"[{service_name}] current_id={current_id}, last_id={last_id}")

        # First run - save status but don't trigger notification
        if last_id is None:
            if update_db:
                await self.star.put_kv_data(kv_key, current_id)
                logger.info(f"[{service_name}] 首次初始化状态: {current_id}")
            
            return {
                'changed': False,  # First run is not a "change"
                'data': status_info.get('raw_status'),
                'type': service_type,
                'indicator': status_info['indicator'],
                'description': status_info['description'],
                'info': status_info
            }

        # Compare with previous status
        status_changed = ignore_cache or (current_id != last_id)

        # Update storage only if changed and update_db is True
        if status_changed and update_db:
            await self.star.put_kv_data(kv_key, current_id)
            logger.info(f"[{service_name}] 状态变化: {last_id} -> {current_id}")
        else:
            logger.debug(f"[{service_name}] 状态未变化 (update_db={update_db})")

        return {
            'changed': status_changed,
            'data': status_info.get('raw_status'),
            'type': service_type,
            'indicator': status_info['indicator'],
            'description': status_info['description'],
            'info': status_info
        }
