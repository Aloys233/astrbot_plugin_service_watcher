import asyncio
from typing import Optional, Dict, Any

import aiohttp
import feedparser
from astrbot.api import logger


class StatusAPIClient:
    """用于从各种来源获取服务状态的 HTTP 客户端。"""

    USER_AGENT = "AstrBot-ServiceWatcher/0.5 (+https://github.com/Aloys233/astrbot_plugin_service_watcher)"

    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建客户端会话。"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                trust_env=True,
                headers={"User-Agent": self.USER_AGENT}
            )
        return self.session

    async def close(self):
        """关闭客户端会话。"""
        if self.session and not self.session.closed:
            await self.session.close()

    RETRY_DELAY = 2  # 网络异常重试前的等待秒数

    async def fetch_json(self, service_name: str, api_url: str) -> Optional[dict]:
        """从 API 获取 JSON 数据（网络异常时自动重试一次）。"""
        for attempt in range(2):
            try:
                session = await self._get_session()
                async with session.get(api_url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status != 200:
                        logger.error(f"[{service_name}] API请求失败: HTTP {response.status}")
                        return None
                    return await response.json()
            except Exception as e:
                if attempt == 0:
                    logger.warning(f"[{service_name}] 获取 JSON 状态失败，即将重试: {repr(e)}")
                    await asyncio.sleep(self.RETRY_DELAY)
                    continue
                import traceback
                logger.warning(f"[{service_name}] 获取 JSON 状态失败: {repr(e)}")
                logger.debug(traceback.format_exc())
                return None
        return None

    async def fetch_rss(self, service_name: str, rss_url: str) -> Optional[dict]:
        """获取并解析 RSS 源（网络异常时自动重试一次）。"""
        for attempt in range(2):
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
                if attempt == 0:
                    logger.warning(f"[{service_name}] 获取 RSS 状态失败，即将重试: {repr(e)}")
                    await asyncio.sleep(self.RETRY_DELAY)
                    continue
                import traceback
                logger.warning(f"[{service_name}] 获取 RSS 状态失败: {repr(e)}")
                logger.debug(traceback.format_exc())
                return None
        return None

    async def fetch_probe(self, service_name: str, probe_url: str) -> Dict[str, Any]:
        """探测 URL 可达性。

        Returns:
            {'reachable': bool, 'status_code': int|None, 'latency_ms': int|None, 'error': str|None}
            网络层失败不会抛异常，而是返回 reachable=False 的结果。
        """
        result: Dict[str, Any] = {
            'reachable': False,
            'status_code': None,
            'latency_ms': None,
            'error': None
        }
        try:
            session = await self._get_session()
            loop = asyncio.get_running_loop()
            start = loop.time()
            async with session.get(probe_url, timeout=aiohttp.ClientTimeout(total=10),
                                   allow_redirects=True) as response:
                # 读取响应体以获得完整的响应周期耗时
                await response.read()
                result['reachable'] = True
                result['status_code'] = response.status
                result['latency_ms'] = int((loop.time() - start) * 1000)
        except Exception as e:
            # 将常见网络错误归纳为简洁的中文描述
            if isinstance(e, asyncio.TimeoutError) or 'Timeout' in type(e).__name__:
                result['error'] = '请求超时'
            elif 'Connector' in type(e).__name__ or isinstance(e, OSError):
                result['error'] = '连接失败/DNS 解析失败'
            else:
                result['error'] = repr(e)[:60]
            logger.debug(f"[{service_name}] 探测失败: {repr(e)}")
        return result


from .adapters import StatusPageAdapter, RSSAdapter, AliyunAdapter, SteamStatAdapter, ProbeAdapter

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
            'aliyun': AliyunAdapter(),
            'steamstat': SteamStatAdapter(),
            'probe': ProbeAdapter()
        }

    async def close(self):
        """清理资源。"""
        await self.api_client.close()

    @staticmethod
    def get_emoji(indicator: str) -> str:
        """获取状态指示器的表情符号。"""
        return StatusChecker.STATUS_EMOJI.get(indicator, '📊')

    def _extract_snapshot(self, service_type: str, status_info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """提取需要持久化的状态快照（用于下次变更时做 diff）。

        仅 statuspage/aliyun 需要快照；statuspage 去掉 updates 时间线以减小体积。
        """
        details = status_info.get('details')
        if not isinstance(details, dict):
            return None
        if service_type == 'statuspage':
            snapshot = {
                'indicator': status_info.get('indicator'),
                'page_url': details.get('page_url'),
                'incidents': details.get('incidents', []),
                'maintenances': details.get('maintenances', []),
            }
            for item in snapshot['incidents'] + snapshot['maintenances']:
                if isinstance(item, dict):
                    item.pop('updates', None)
            return snapshot
        if service_type == 'aliyun':
            return {'indicator': status_info.get('indicator'), 'events': details.get('events', [])}
        return None

    async def check_service(
            self,
            service_name: str,
            api_url: str,
            service_type: str = "statuspage",
            ignore_cache: bool = False,
            update_db: bool = True
    ) -> Optional[Dict[str, Any]]:
        """检查服务状态并检测变更。

        Args:
            service_name: 服务名称
            api_url: 获取状态的 URL
            service_type: 服务类型 (statuspage/rss/aliyun/steamstat/probe)
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
        # key 中包含服务类型：类型或数据源调整后旧缓存自然失效，避免升级后误报变更
        kv_key = f"service_watcher_{service_name}_{service_type}_last_id"
        snapshot_key = f"service_watcher_{service_name}_{service_type}_last_snapshot"
        last_id = await self.star.get_kv_data(kv_key, None)
        last_snapshot = await self.star.get_kv_data(snapshot_key, None)

        # 调试：记录状态
        logger.debug(f"[{service_name}] current_id={current_id}, last_id={last_id}")

        # 首次运行 - 保存状态但不触发通知
        if last_id is None:
            if update_db:
                await self.star.put_kv_data(kv_key, current_id)
                snapshot = self._extract_snapshot(service_type, status_info)
                if snapshot is not None:
                    await self.star.put_kv_data(snapshot_key, snapshot)
                logger.info(f"[{service_name}] 首次初始化状态: {current_id}")

            return {
                'changed': False,  # 首次运行不算作“变更”
                'data': status_info.get('raw_status'),
                'type': service_type,
                'indicator': status_info['indicator'],
                'description': status_info['description'],
                'info': status_info,
                'previous': last_snapshot,
            }

        # 与上一次状态进行比较
        status_changed = ignore_cache or (current_id != last_id)

        # 仅当状态变更且 update_db 为 True 时更新存储
        if status_changed and update_db:
            await self.star.put_kv_data(kv_key, current_id)
            snapshot = self._extract_snapshot(service_type, status_info)
            if snapshot is not None:
                await self.star.put_kv_data(snapshot_key, snapshot)
            logger.info(f"[{service_name}] 状态变化: {last_id} -> {current_id}")
        else:
            logger.debug(f"[{service_name}] 状态未变化 (update_db={update_db})")

        return {
            'changed': status_changed,
            'data': status_info.get('raw_status'),
            'type': service_type,
            'indicator': status_info['indicator'],
            'description': status_info['description'],
            'info': status_info,
            'previous': last_snapshot,
        }
