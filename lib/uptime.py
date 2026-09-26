"""服务可用性历史统计：按天聚合检查结果，支持 7/30 天可用率。"""

from datetime import date, timedelta
from typing import Any, Dict

from astrbot.api import logger

# 保留的最大天数（滚动窗口）
RETENTION_DAYS = 30

KV_PREFIX = "service_watcher_uptime_"

# 分类: ok（正常）/ degraded（降级或维护）/ down（故障或获取失败）


def classify(indicator: str, check_ok: bool) -> str:
    """将一次检查结果归入 ok/degraded/down。"""
    if not check_ok:
        return 'down'
    text = str(indicator or '').strip().lower()
    if text in ('none', 'operational', 'rss_new'):
        return 'ok'
    if text in ('major', 'critical', 'partial_outage'):
        return 'down'
    return 'degraded'


def _kv_key(service_key: str) -> str:
    return f"{KV_PREFIX}{service_key}"


def _prune(data: Dict[str, Any], today: date) -> None:
    """只保留最近 RETENTION_DAYS 天的数据。"""
    cutoff = (today - timedelta(days=RETENTION_DAYS - 1)).isoformat()
    for day in [d for d in data if str(d) < cutoff]:
        data.pop(day, None)


async def record(star, service_key: str, indicator: str, check_ok: bool) -> None:
    """记录一次检查结果（由监控循环调用，dashboard 刷新不记录）。"""
    try:
        today = date.today().isoformat()
        data = await star.get_kv_data(_kv_key(service_key), None)
        data = data if isinstance(data, dict) else {}
        day = data.setdefault(today, {'ok': 0, 'degraded': 0, 'down': 0})
        day[classify(indicator, check_ok)] = day.get(classify(indicator, check_ok), 0) + 1
        _prune(data, date.today())
        await star.put_kv_data(_kv_key(service_key), data)
    except Exception as e:
        logger.warning(f"[{service_key}] 记录可用性数据失败: {e}")


async def summary(star, service_key: str, days: int = 7) -> Dict[str, Any]:
    """返回最近 N 天的可用率统计。

    Returns:
        {'total': 总检查次数, 'ok': 正常次数, 'ratio': 可用率(0-100)，无数据时为 None}
    """
    data = await star.get_kv_data(_kv_key(service_key), None)
    if not isinstance(data, dict) or not data:
        return {'total': 0, 'ok': 0, 'ratio': None}

    today = date.today()
    total = 0
    ok = 0
    for offset in range(days):
        day = (today - timedelta(days=offset)).isoformat()
        entry = data.get(day)
        if not isinstance(entry, dict):
            continue
        day_total = sum(entry.get(k, 0) for k in ('ok', 'degraded', 'down'))
        total += day_total
        ok += entry.get('ok', 0)

    ratio = round(ok * 100.0 / total, 2) if total else None
    return {'total': total, 'ok': ok, 'ratio': ratio}
