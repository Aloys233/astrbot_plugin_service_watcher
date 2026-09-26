from abc import ABC, abstractmethod
import re
from typing import Dict, Optional, Any, List
from urllib.parse import urlparse, parse_qs

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

    # 事件/维护状态的中文映射（仅用于展示；变更检测仍使用原始 status）
    STATUS_CN = {
        'investigating': '调查中',
        'identified': '已定位',
        'monitoring': '监控中',
        'resolved': '已解决',
        'postmortem': '复盘中',
        'scheduled': '已排期',
        'in_progress': '进行中',
        'verifying': '验证中',
        'completed': '已完成',
        'cancelled': '已取消'
    }

    # 影响等级的中文映射（固定词表，静态映射即可）
    IMPACT_CN = {
        'none': '无',
        'maintenance': '维护',
        'minor': '轻微',
        'major': '较重',
        'critical': '严重'
    }

    @classmethod
    def status_cn(cls, status: Any) -> str:
        """事件/维护状态的中文展示文本；未知状态返回原文。"""
        text = str(status or '').strip()
        return cls.STATUS_CN.get(text.lower(), text) or '未知'

    @classmethod
    def impact_cn(cls, impact: Any) -> str:
        """影响等级的中文展示文本；未知等级返回原文。"""
        text = str(impact or '').strip()
        return cls.IMPACT_CN.get(text.lower(), text) or '未知'

    @staticmethod
    def _build_timeline(updates: Any, limit: int = 20) -> List[Dict[str, Any]]:
        """提取事件/维护的更新时间线（最新的在前）。"""
        if not isinstance(updates, list):
            return []
        timeline = []
        for update in updates:
            if not isinstance(update, dict):
                continue
            timeline.append({
                'status': update.get('status'),
                'body': update.get('body'),
                'created_at': update.get('created_at') or update.get('display_at'),
            })
        return timeline[:limit]

    async def fetch_status(self, client, service_name: str, api_url: str) -> Optional[Dict[str, Any]]:
        data = await client.fetch_json(service_name, api_url)
        if not data:
            return None

        status = data.get('status', {})
        indicator = status.get('indicator', 'none')
        raw_description = status.get('description', 'Unknown')
        incidents = data.get('incidents', []) if isinstance(data.get('incidents'), list) else []
        maintenances = data.get('scheduled_maintenances', []) if isinstance(
            data.get('scheduled_maintenances'), list) else []
        page_url = data.get('page', {}).get('url')

        # 翻译描述
        description = self.STATUS_TRANSLATIONS.get(raw_description, raw_description)

        normalized_incidents = []
        incident_signature_parts = []
        for incident in incidents:
            if not isinstance(incident, dict):
                continue

            updates = incident.get('incident_updates', [])
            latest_update = updates[0] if isinstance(updates, list) and updates and isinstance(updates[0], dict) else {}

            incident_id = str(incident.get('id', 'unknown'))
            incident_status = incident.get('status', 'unknown')
            incident_impact = incident.get('impact', 'unknown')
            incident_updated = incident.get('updated_at') or latest_update.get('updated_at') or latest_update.get(
                'created_at')
            incident_update_body = latest_update.get('body')
            incident_signature_parts.append(
                f"{incident_id}:{incident_status}:{incident_impact}:{incident_updated}:{incident_update_body}"
            )

            normalized_incidents.append({
                'id': incident_id,
                'title': incident.get('name', '未知事件'),
                'status': incident_status,
                'status_cn': self.status_cn(incident_status),
                'impact': incident.get('impact', 'unknown'),
                'impact_cn': self.impact_cn(incident.get('impact', 'unknown')),
                'created_at': incident.get('created_at'),
                'updated_at': incident_updated,
                'summary': latest_update.get('body'),
                'link': incident.get('shortlink'),
                'updates': self._build_timeline(updates)
            })

        incident_signature = ",".join(sorted(incident_signature_parts)) or "no_incidents"

        # 计划维护也纳入状态签名，避免开始/结束维护时漏报
        maintenance_parts = []
        normalized_maintenances = []
        for maintenance in maintenances:
            if not isinstance(maintenance, dict):
                continue
            m_id = str(maintenance.get('id', 'unknown'))
            m_status = maintenance.get('status', 'unknown')
            maintenance_parts.append(f"{m_id}:{m_status}")
            normalized_maintenances.append({
                'id': m_id,
                'title': maintenance.get('name', '计划维护'),
                'status': m_status,
                'status_cn': self.status_cn(m_status),
                'scheduled_for': maintenance.get('scheduled_for'),
                'updated_at': maintenance.get('updated_at'),
                'link': maintenance.get('shortlink'),
                'updates': self._build_timeline(maintenance.get('incident_updates'))
            })

        maintenance_signature = ",".join(sorted(maintenance_parts)) or "no_maintenances"

        return {
            'indicator': indicator,
            'description': description,
            'raw_status': data,
            'id': f"{indicator}|{description}|{incident_signature}|{maintenance_signature}",
            'details': {
                'page_url': page_url,
                'incident_count': len(normalized_incidents),
                'incidents': normalized_incidents,
                'maintenance_count': len(normalized_maintenances),
                'maintenances': normalized_maintenances
            }
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
        entry_id = latest.get('id') or latest.get('published') or latest.get('updated') or latest.get('link')

        return {
            'indicator': 'rss_new',
            'description': latest.get('title', '新动态'),
            'id': entry_id,
            'entry': latest,
            'raw_status': None,  # RSS 数据通常太大/太复杂而无法作为原始状态存储
            'details': {
                'title': latest.get('title'),
                'published': latest.get('published') or latest.get('updated'),
                'author': latest.get('author'),
                'link': latest.get('link'),
                'summary': latest.get('summary') or latest.get('description')
            }
        }


class SteamStatAdapter(BaseAdapter):
    """SteamStat.us JSON 的适配器。"""

    SERVICE_ALIASES = {
        "web_api": "webapi",
        "api": "webapi",
        "csgo": "cs2",
        "counterstrike2": "cs2",
        "counterstrike": "cs2",
        "dota": "dota2"
    }

    LEVEL_MAP = {
        "normal": "none",
        "ok": "none",
        "low load": "none",
        "medium load": "minor",
        "high load": "critical",
        "very slow": "critical"
    }

    @staticmethod
    def _normalize_key(value: str) -> str:
        text = re.sub(r"[^a-z0-9]+", "", value.lower())
        return text or value.lower()

    @classmethod
    def _canonical_service(cls, value: str) -> str:
        normalized = cls._normalize_key(value)
        return cls.SERVICE_ALIASES.get(normalized, normalized)

    @classmethod
    def _indicator_for_level(cls, level: str, text: str = "") -> str:
        if level is None:
            level = ""
        normalized = str(level).strip().lower()
        if normalized.isdigit():
            return "none" if int(normalized) == 0 else "minor"
        for key, indicator in cls.LEVEL_MAP.items():
            if key in normalized:
                return indicator
        normalized_text = str(text).strip().lower()
        for key, indicator in cls.LEVEL_MAP.items():
            if key in normalized_text:
                return indicator
        return "minor"

    @staticmethod
    def _service_from_query(api_url: str) -> str:
        query = parse_qs(urlparse(api_url).query)
        service = query.get("service", [])
        if service:
            return str(service[0])
        return ""

    async def fetch_status(self, client, service_name: str, api_url: str) -> Optional[Dict[str, Any]]:
        data = await client.fetch_json(service_name, api_url)
        if not data:
            return None

        service_hint = self._service_from_query(api_url)
        service_key = self._canonical_service(service_hint) if service_hint else ""

        services = data.get("services", [])
        if not isinstance(services, list):
            services = []

        matched = None
        for entry in services:
            if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                continue
            key = self._canonical_service(str(entry[0]))
            if service_key and key != service_key:
                continue
            matched = entry
            service_key = key
            break

        if not matched:
            logger.warning(f"[{service_name}] SteamStat 服务未找到: {service_hint or service_key}")
            return None

        level = str(matched[1])
        text = str(matched[2]) if len(matched) > 2 else level
        indicator = self._indicator_for_level(level, text)
        display_name = service_key or service_name
        description = f"{display_name}: {text}"
        status_id = f"{service_key}|{level}|{text}"

        return {
            "indicator": indicator,
            "description": description,
            "id": status_id,
            "raw_status": data,
            "details": {
                "service": service_key,
                "level": level,
                "text": text
            }
        }


class AliyunAdapter(BaseAdapter):
    """阿里云状态 API 的适配器。"""

    @staticmethod
    def _pick(event: Dict[str, Any], keys: List[str], default: str = "") -> str:
        for key in keys:
            value = event.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return default

    @classmethod
    def _normalize_event(cls, event: Dict[str, Any]) -> Dict[str, str]:
        return {
            'id': cls._pick(event, ['id', 'eventId'], 'unknown'),
            'title': cls._pick(event, ['name', 'title', 'eventName', 'subject'], '未命名事件'),
            'status': cls._pick(event, ['status', 'state', 'eventStatus'], 'unknown'),
            'severity': cls._pick(event, ['level', 'severity', 'eventLevel', 'grade'], 'unknown'),
            'started_at': cls._pick(event, ['startTime', 'start_time', 'gmtCreate', 'createTime']),
            'updated_at': cls._pick(event, ['updateTime', 'gmtModified', 'modifiedTime']),
            'link': cls._pick(event, ['url', 'link', 'detailUrl'])
        }

    @staticmethod
    def _infer_indicator(events: List[Dict[str, str]]) -> str:
        text = " ".join(
            f"{event.get('severity', '')} {event.get('status', '')} {event.get('title', '')}"
            for event in events
        ).lower()

        if any(keyword in text for keyword in ['critical', 'severe', 'high', 'major', '严重', '紧急']):
            return 'major'
        return 'minor'

    async def fetch_status(self, client, service_name: str, api_url: str) -> Optional[Dict[str, Any]]:
        data = await client.fetch_json(service_name, api_url)
        if not data:
            return None

        # 阿里云返回 {"data": [], "total": 0, "success": true, ...}
        # data 是正在进行的事件列表
        events = data.get('data', [])
        if not isinstance(events, list):
            events = []

        if not events:
            return {
                'indicator': 'none',
                'description': '所有系统运行正常',
                'id': 'empty_list',
                'raw_status': data,
                'details': {
                    'event_count': 0,
                    'events': []
                }
            }

        normalized_events = []
        for event in events:
            if isinstance(event, dict):
                normalized_events.append(self._normalize_event(event))

        # 将事件关键信息加入签名，避免只比较 ID 时漏掉状态更新
        event_signature = ",".join(sorted(
            f"{event.get('id', 'unknown')}:{event.get('status', 'unknown')}:{event.get('updated_at', '')}"
            for event in normalized_events
        )) or "unknown"

        indicator = self._infer_indicator(normalized_events)
        first_title = normalized_events[0]['title'] if normalized_events else '未知事件'

        return {
            'indicator': indicator,
            'description': f"{len(normalized_events)} 个活跃事件（例如：{first_title}）",
            'id': f"events_{event_signature}",
            'raw_status': data,
            'details': {
                'event_count': len(normalized_events),
                'events': normalized_events
            }
        }


class ProbeAdapter(BaseAdapter):
    """通用 HTTP 探测适配器。

    直接 GET 目标 URL，根据响应判断服务是否可达。适用于没有官方状态页的
    服务（如国内大部分平台）：任何 HTTP 响应都证明服务在线，即使返回
    401/404 也说明服务本身可达（未带凭证时这是预期响应）。
    """

    async def fetch_status(self, client, service_name: str, api_url: str) -> Optional[Dict[str, Any]]:
        result = await client.fetch_probe(service_name, api_url)

        reachable = result.get('reachable', False)
        status_code = result.get('status_code')
        latency_ms = result.get('latency_ms')
        error = result.get('error')

        if reachable:
            if status_code is None or status_code >= 500 or status_code == 429:
                indicator = 'major'
                state = '服务异常'
            else:
                indicator = 'none'
                state = '运行正常'
            description = f"{state} (HTTP {status_code}, {latency_ms}ms)"
            status_id = f"probe|{indicator}|{status_code}"
        else:
            # 网络层失败：可能是服务故障，也可能是监控机自身网络问题
            indicator = 'critical'
            description = f"无法连接 ({error or '未知错误'})"
            status_id = f"probe|critical|unreachable"

        return {
            'indicator': indicator,
            'description': description,
            'id': status_id,
            'raw_status': None,
            'details': {
                'target': api_url,
                'reachable': reachable,
                'status_code': status_code,
                'latency_ms': latency_ms,
                'error': error
            }
        }
