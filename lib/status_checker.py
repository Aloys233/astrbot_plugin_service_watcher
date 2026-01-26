import asyncio
from typing import Optional, Dict

import aiohttp
import feedparser
from astrbot.api import logger


class StatusAPIClient:
    """用于从各种来源获取服务状态的 HTTP 客户端。"""

    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建客户端会话。"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(trust_env=True)
        return self.session

    async def close(self):
        """关闭客户端会话。"""
        if self.session and not self.session.closed:
            await self.session.close()

    async def fetch_json(self, service_name: str, api_url: str) -> Optional[dict]:
        """从 API 获取 JSON 数据。"""
        try:
            session = await self._get_session()
            async with session.get(api_url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    logger.error(f"[{service_name}] API请求失败: HTTP {response.status}")
                    return None
                return await response.json()
        except Exception as e:
            import traceback
            logger.warning(f"[{service_name}] 获取 JSON 状态失败: {repr(e)}")
            logger.debug(traceback.format_exc())
            return None

    async def fetch_rss(self, service_name: str, rss_url: str) -> Optional[dict]:
        """获取并解析 RSS 源。"""
        try:
            session = await self._get_session()
            async with session.get(rss_url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    logger.error(f"[{service_name}] RSS请求失败: HTTP {response.status}")
                    return None
                content = await response.read()

                # 在执行器中解析以避免阻塞事件循环
                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(None, feedparser.parse, content)
        except Exception as e:
            import traceback
            logger.warning(f"[{service_name}] 获取 RSS 状态失败: {repr(e)}")
            logger.debug(traceback.format_exc())
            return None


from .adapters import StatusPageAdapter, RSSAdapter, AliyunAdapter

class StatusChecker:
    """检查服务状态并检测多种类型的变更。"""

    # 状态表情映射
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
        """初始化状态检查器，使用 Star 实例进行 KV 存储。
        
        Args:
            star: 提供 get_kv_data/put_kv_data 方法的 Star 实例
        """
        self.star = star
        self.api_client = StatusAPIClient()
        self.adapters = {
            'statuspage': StatusPageAdapter(),
            'rss': RSSAdapter(),
            'aliyun': AliyunAdapter()
        }

    async def close(self):
        """清理资源。"""
        await self.api_client.close()

    @staticmethod
    def get_emoji(indicator: str) -> str:
        """获取状态指示器的表情符号。"""
        return StatusChecker.STATUS_EMOJI.get(indicator, '📊')

    async def check_service(
            self,
            service_name: str,
            api_url: str,
            service_type: str = "statuspage",
            ignore_cache: bool = False,
            update_db: bool = True
    ) -> Optional[Dict[str, any]]:
        """检查服务状态并检测变更。
        
        Args:
            service_name: 服务名称
            api_url: 获取状态的 URL
            service_type: 服务类型 (statuspage/rss/aliyun)
            ignore_cache: 如果为 True，则忽略 last_id 比较以确定 changed 标志
            update_db: 如果为 True，则使用新状态 ID 更新 KV 存储
        """
        adapter = self.adapters.get(service_type)
        if not adapter:
            logger.error(f"[{service_name}] Unknown service type: {service_type}")
            return None

        status_info = await adapter.fetch_status(self.api_client, service_name, api_url)

        if not status_info:
            return None

        current_id = status_info['id']

        # 检查 KV 存储中的上一次状态（使用 Star 的异步 KV 方法）
        kv_key = f"service_watcher_{service_name}_last_id"
        last_id = await self.star.get_kv_data(kv_key, None)

        # 调试：记录状态
        logger.debug(f"[{service_name}] current_id={current_id}, last_id={last_id}")

        # 首次运行 - 保存状态但不触发通知
        if last_id is None:
            if update_db:
                await self.star.put_kv_data(kv_key, current_id)
                logger.info(f"[{service_name}] 首次初始化状态: {current_id}")
            
            return {
                'changed': False,  # 首次运行不算作“变更”
                'data': status_info.get('raw_status'),
                'type': service_type,
                'indicator': status_info['indicator'],
                'description': status_info['description'],
                'info': status_info
            }

        # 与上一次状态进行比较
        status_changed = ignore_cache or (current_id != last_id)

        # 仅当状态变更且 update_db 为 True 时更新存储
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
