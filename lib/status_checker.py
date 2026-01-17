import aiohttp
import asyncio
import feedparser
from typing import Optional, Dict, Any
from astrbot.api import logger


class StatusAPIClient:
    """HTTP client for fetching service status from various sources."""

    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create client session."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
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
            logger.error(f"[{service_name}] 获取 JSON 状态失败: {e}")
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
            logger.error(f"[{service_name}] 获取 RSS 状态失败: {e}")
            return None


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

    async def close(self):
        """Cleanup resources."""
        await self.api_client.close()

    def get_status_info(self, data: Any, service_type: str) -> Dict[str, Any]:
        """Extract status information based on service type."""
        if service_type == "statuspage":
            status = data.get('status', {})
            indicator = status.get('indicator', 'none')
            description = status.get('description', 'Unknown')
            return {
                'indicator': indicator,
                'description': description,
                'raw_status': status,
                'id': f"{indicator}|{description}"
            }
        elif service_type == "rss":
            entries = data.get('entries', [])
            if not entries:
                return {
                    'indicator': 'none',
                    'description': 'No updates',
                    'id': 'empty'
                }
            latest = entries[0]
            # Use entry ID or published date as unique identifier
            entry_id = latest.get('id') or latest.get('published') or latest.get('link')
            return {
                'indicator': 'rss_new',
                'description': latest.get('title', '新动态'),
                'id': entry_id,
                'entry': latest
            }
        return {'indicator': 'unknown', 'description': 'Unknown type', 'id': 'unknown'}

    @staticmethod
    def get_emoji(indicator: str) -> str:
        """Get emoji for status indicator."""
        return StatusChecker.STATUS_EMOJI.get(indicator, '📊')

    async def check_service(
            self,
            service_name: str,
            api_url: str,
            service_type: str = "statuspage",
            ignore_cache: bool = False
    ) -> Optional[Dict[str, any]]:
        """Check service status and detect changes."""
        if service_type == "statuspage":
            data = await self.api_client.fetch_json(service_name, api_url)
        else:
            data = await self.api_client.fetch_rss(service_name, api_url)

        if not data:
            return None

        # Get current status
        status_info = self.get_status_info(data, service_type)
        current_id = status_info['id']

        # Check KV storage for last status (using Star's async KV methods)
        kv_key = f"service_watcher_{service_name}_last_id"
        last_id = await self.star.get_kv_data(kv_key, None)

        # Debug: log the state
        logger.debug(f"[{service_name}] current_id={current_id}, last_id={last_id}")

        # First run - save status but don't trigger notification
        if last_id is None:
            await self.star.put_kv_data(kv_key, current_id)
            logger.info(f"[{service_name}] 首次初始化状态: {current_id}")
            return {
                'changed': False,  # First run is not a "change"
                'data': data,
                'type': service_type,
                'indicator': status_info['indicator'],
                'description': status_info['description'],
                'info': status_info
            }

        # Compare with previous status
        status_changed = ignore_cache or (current_id != last_id)

        # Update storage only if changed
        if status_changed:
            await self.star.put_kv_data(kv_key, current_id)
            logger.info(f"[{service_name}] 状态变化: {last_id} -> {current_id}")
        else:
            logger.debug(f"[{service_name}] 状态未变化")

        return {
            'changed': status_changed,
            'data': data,
            'type': service_type,
            'indicator': status_info['indicator'],
            'description': status_info['description'],
            'info': status_info
        }
