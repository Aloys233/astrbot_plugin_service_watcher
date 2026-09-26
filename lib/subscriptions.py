"""会话自助订阅管理：按服务维护接收通知的会话列表。

数据存储于 KV（key: service_watcher_subscriptions）：
    {service_key: [unified_msg_origin, ...]}
"""

from typing import Any, Dict, List, Optional

from astrbot.api import logger

SUBSCRIPTIONS_KEY = "service_watcher_subscriptions"


async def _load(star) -> Dict[str, List[str]]:
    data = await star.get_kv_data(SUBSCRIPTIONS_KEY, None)
    return data if isinstance(data, dict) else {}


async def _save(star, data: Dict[str, List[str]]) -> None:
    await star.put_kv_data(SUBSCRIPTIONS_KEY, data)


async def subscribe(star, service_key: str, umo: str) -> bool:
    """订阅服务到指定会话；已订阅时返回 False。"""
    data = await _load(star)
    targets = data.setdefault(service_key, [])
    if umo in targets:
        return False
    targets.append(umo)
    await _save(star, data)
    logger.debug(f"会话 {umo} 已订阅服务 {service_key}")
    return True


async def unsubscribe(star, service_key: str, umo: str) -> bool:
    """退订服务；未订阅时返回 False。"""
    data = await _load(star)
    targets = data.get(service_key)
    if not targets or umo not in targets:
        return False
    targets.remove(umo)
    if not targets:
        data.pop(service_key, None)
    await _save(star, data)
    logger.debug(f"会话 {umo} 已退订服务 {service_key}")
    return True


async def get_targets(star, service_key: str) -> List[str]:
    """获取订阅了指定服务的会话列表。"""
    data = await _load(star)
    return list(data.get(service_key, []))


async def get_all_targets(star) -> List[str]:
    """获取所有订阅会话（去重），用于每日摘要等全局推送。"""
    data = await _load(star)
    seen = set()
    result: List[str] = []
    for targets in data.values():
        for umo in targets:
            if umo not in seen:
                seen.add(umo)
                result.append(umo)
    return result


async def list_for(star, umo: str) -> List[str]:
    """列出指定会话订阅的所有服务 key。"""
    data = await _load(star)
    return sorted(key for key, targets in data.items() if umo in targets)
