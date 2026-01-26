from abc import ABC, abstractmethod
from typing import Dict, Optional, Any

from astrbot.api import logger


class BaseAdapter(ABC):
    """服务状态适配器的抽象基类。"""

    @abstractmethod
    async def fetch_status(self, client, service_name: str, api_url: str) -> Optional[Dict[str, Any]]:
        """
        从服务获取并解析状态。
        
        Args:
            client: StatusAPIClient 实例
            service_name: 服务名称
            api_url: 获取状态的 URL
            
        Returns:
            包含标准化状态信息的字典，如果失败则返回 None。
            标准键: 'indicator', 'description', 'id', 'raw_status', 'entry' (可选)
        """
        pass


class StatusPageAdapter(BaseAdapter):
    """标准 StatusPage.io JSON API 的适配器。"""

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

        # 翻译描述
        description = self.STATUS_TRANSLATIONS.get(raw_description, raw_description)

        return {
            'indicator': indicator,
            'description': description,
            'raw_status': status,
            'id': f"{indicator}|{description}"
        }


class RSSAdapter(BaseAdapter):
    """RSS/Atom 源的适配器。"""

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
        # 使用条目 ID 或发布日期作为唯一标识符
        entry_id = latest.get('id') or latest.get('published') or latest.get('link')

        return {
            'indicator': 'rss_new',
            'description': latest.get('title', '新动态'),
            'id': entry_id,
            'entry': latest,
            'raw_status': None  # RSS 数据通常太大/太复杂而无法作为原始状态存储
        }


class AliyunAdapter(BaseAdapter):
    """阿里云状态 API 的适配器。"""

    async def fetch_status(self, client, service_name: str, api_url: str) -> Optional[Dict[str, Any]]:
        data = await client.fetch_json(service_name, api_url)
        if not data:
            return None

        # 阿里云返回 {"data": [], "total": 0, "success": true, ...}
        # data 是正在进行的事件列表
        events = data.get('data', [])

        if not events:
            return {
                'indicator': 'none',
                'description': '所有系统运行正常',
                'id': 'empty_list',
                'raw_status': data
            }

        # 如果有事件，取第一个或有效的摘要
        # 我们将使用事件 ID 列表作为状态的唯一 ID
        event_ids = ",".join(sorted(str(e.get('id', 'unknown')) for e in events))

        return {
            'indicator': 'minor',  # 如果有事件，假设为轻微问题
            'description': f"{len(events)} 个活跃事件",
            'id': f"events_{event_ids}",
            'raw_status': data
        }
