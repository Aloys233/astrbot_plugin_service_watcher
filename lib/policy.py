"""推送灵敏度策略：决定一次状态变化是否值得打扰用户。"""

from typing import Any, List, Optional

# 影响等级 -> 严重度排名（数值越大越严重）
SEVERITY_RANK = {
    'none': 0,
    'operational': 0,
    'rss_new': 0,
    'minor': 1,
    'maintenance': 1,
    'under_maintenance': 1,
    'degraded_performance': 1,
    'partial_outage': 2,
    'major': 2,
    'critical': 3,
}

_VALID_POLICIES = {'low', 'medium', 'high'}


def _rank(indicator: Any) -> int:
    return SEVERITY_RANK.get(str(indicator or '').strip().lower(), 1)


def normalize_policy(policy: Any) -> str:
    """规范化策略值，非法值回退为 high（保持旧行为）。"""
    text = str(policy or '').strip().lower()
    return text if text in _VALID_POLICIES else 'high'


def _is_recovered(prev_indicator: Any, cur_indicator: Any) -> bool:
    """之前处于异常状态、现在恢复正常。"""
    return _rank(prev_indicator) > 0 and _rank(cur_indicator) == 0


def _has_new_items(diff_lines: Optional[List[str]]) -> bool:
    """diff 中是否出现新增事件/维护。"""
    if not diff_lines:
        return False
    return any('🆕' in line or '🔧 新增维护' in line for line in diff_lines)


def should_notify(
    policy: Any,
    prev_indicator: Any,
    cur_indicator: Any,
    diff_lines: Optional[List[str]] = None,
    service_type: str = '',
) -> bool:
    """根据推送灵敏度判断是否发送通知。

    Args:
        policy: low / medium / high
        prev_indicator: 上一次的整体状态指示器（快照中记录）
        cur_indicator: 当前的整体状态指示器
        diff_lines: 快照差异描述行（statuspage/aliyun 提供）
        service_type: 服务类型；rss 属于内容订阅，始终推送

    Returns:
        True 表示应发送通知。
    """
    if service_type == 'rss':
        return True

    level = normalize_policy(policy)
    if level == 'high':
        return True

    if level == 'low':
        # 仅严重故障或从异常中恢复
        return _rank(cur_indicator) >= 2 or _is_recovered(prev_indicator, cur_indicator)

    # medium：影响升级、恢复、或出现新增事件/维护
    if _is_recovered(prev_indicator, cur_indicator):
        return True
    if _rank(cur_indicator) > _rank(prev_indicator):
        return True
    return _has_new_items(diff_lines)
