"""状态快照对比工具，用于生成"本次变化"通知内容。"""

from typing import Any, Dict, List, Optional

from .text import clean_text as _clean_text, clean_summary as _clean_summary


def _status_display(item: Dict[str, Any]) -> str:
    """事件/维护状态的展示文本：优先中文映射，回退原文。"""
    return _clean_text(item.get('status_cn') or item.get('status'), 'unknown')


def _impact_display(item: Dict[str, Any]) -> str:
    """影响等级的展示文本：优先中文映射，回退原文。"""
    return _clean_text(item.get('impact_cn') or item.get('impact'), 'unknown')


def _index_by_id(items: Any) -> Dict[str, Dict[str, Any]]:
    """将事件/维护列表转为按 id 索引的字典，忽略非法条目。"""
    if not isinstance(items, list):
        return {}
    return {
        str(item.get("id")): item
        for item in items
        if isinstance(item, dict) and item.get("id") is not None
    }


def _statuspage_report(
    prev_details: Optional[Dict[str, Any]],
    cur_details: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """对比两次 StatusPage 快照。

    Returns:
        包含 'lines'（变化描述行）、'unchanged_incidents'、'unchanged_maintenances'
        的字典；无任何差异时返回 None。
    """
    prev_incidents = _index_by_id((prev_details or {}).get("incidents"))
    cur_incidents = _index_by_id((cur_details or {}).get("incidents"))
    prev_maintenances = _index_by_id((prev_details or {}).get("maintenances"))
    cur_maintenances = _index_by_id((cur_details or {}).get("maintenances"))

    lines: List[str] = []
    unchanged_incidents = 0
    unchanged_maintenances = 0

    # 新增事件
    for incident_id, cur in cur_incidents.items():
        if incident_id in prev_incidents:
            continue
        lines.append(f"🆕 新增事件: {_clean_text(cur.get('title'), '未知事件')}")
        lines.append(
            f"   状态: {_status_display(cur)}"
            f" | 影响: {_impact_display(cur)}"
        )
        lines.append(f"   说明: {_clean_summary(cur.get('summary'))}")
        link = _clean_text(cur.get("link"), "")
        if link:
            lines.append(f"   链接: {link}")

    # 已解决/移除事件（API 只返回未解决事件，消失即解决）
    for incident_id, prev in prev_incidents.items():
        if incident_id in cur_incidents:
            continue
        lines.append(f"✅ 事件已解决: {_clean_text(prev.get('title'), '未知事件')}")

    # 事件更新（状态/影响/最新说明任一变化；对比基于原始英文字段，
    # 展示时才中文化，避免新旧版本快照 status_cn 缺失导致的假差异）
    for incident_id, cur in cur_incidents.items():
        prev = prev_incidents.get(incident_id)
        if prev is None:
            continue
        prev_status_raw = _clean_text(prev.get("status"), "unknown")
        cur_status_raw = _clean_text(cur.get("status"), "unknown")
        prev_impact_raw = _clean_text(prev.get("impact"), "unknown")
        cur_impact_raw = _clean_text(cur.get("impact"), "unknown")
        prev_summary = _clean_text(prev.get("summary"), "")
        cur_summary = _clean_text(cur.get("summary"), "")

        if prev_status_raw == cur_status_raw and prev_impact_raw == cur_impact_raw \
                and prev_summary == cur_summary:
            unchanged_incidents += 1
            continue

        prev_state = _status_display(prev)
        cur_state = _status_display(cur)
        state_line = f"   状态: {prev_state} → {cur_state}"
        if prev_impact_raw != cur_impact_raw:
            state_line += f" | 影响: {_impact_display(prev)} → {_impact_display(cur)}"
        lines.append(f"🔄 事件更新: {_clean_text(cur.get('title'), '未知事件')}")
        lines.append(state_line)
        lines.append(f"   最新说明: {_clean_summary(cur.get('summary'))}")
        link = _clean_text(cur.get("link"), "")
        if link:
            lines.append(f"   链接: {link}")

    # 维护变化：新增/取消/状态变化
    for maintenance_id, cur in cur_maintenances.items():
        if maintenance_id not in prev_maintenances:
            lines.append(f"🔧 新增维护: {_clean_text(cur.get('title'), '计划维护')}")
            lines.append(f"   计划时间: {_clean_text(cur.get('scheduled_for'), '-')}")
            continue
        prev = prev_maintenances[maintenance_id]
        if _clean_text(prev.get("status"), "unknown") != _clean_text(cur.get("status"), "unknown"):
            lines.append(f"🔧 维护状态更新: {_clean_text(cur.get('title'), '计划维护')}")
            lines.append(f"   状态: {_status_display(prev)} → {_status_display(cur)}")
        else:
            unchanged_maintenances += 1

    for maintenance_id, prev in prev_maintenances.items():
        if maintenance_id not in cur_maintenances:
            lines.append(f"🔧 维护已取消/移除: {_clean_text(prev.get('title'), '计划维护')}")

    if not lines:
        return None
    return {
        'lines': lines,
        'unchanged_incidents': unchanged_incidents,
        'unchanged_maintenances': unchanged_maintenances,
    }


def diff_statuspage(
    prev_details: Optional[Dict[str, Any]],
    cur_details: Optional[Dict[str, Any]],
) -> Optional[List[str]]:
    """对比两次 StatusPage 快照，返回变化描述行列表；无差异返回 None。"""
    report = _statuspage_report(prev_details, cur_details)
    return report['lines'] if report else None


def statuspage_unchanged_summary(
    prev_details: Optional[Dict[str, Any]],
    cur_details: Optional[Dict[str, Any]],
) -> Optional[str]:
    """返回未变化部分的汇总描述，如 "其余 3 个事件、计划维护 25 项"。"""
    report = _statuspage_report(prev_details, cur_details)
    if not report:
        return None
    parts = []
    if report['unchanged_incidents']:
        parts.append(f"其余 {report['unchanged_incidents']} 个事件")
    if report['unchanged_maintenances']:
        parts.append(f"计划维护 {report['unchanged_maintenances']} 项")
    return "、".join(parts) if parts else None


def _aliyun_report(
    prev_details: Optional[Dict[str, Any]],
    cur_details: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """对比两次阿里云事件快照。

    Returns:
        包含 'lines'（变化描述行）和 'unchanged_events' 的字典；
        无任何差异时返回 None。
    """
    prev_events = _index_by_id((prev_details or {}).get("events"))
    cur_events = _index_by_id((cur_details or {}).get("events"))

    lines: List[str] = []
    unchanged_events = 0

    for event_id, cur in cur_events.items():
        if event_id not in prev_events:
            lines.append(f"🆕 新增事件: {_clean_text(cur.get('title'), '未命名事件')}")
            lines.append(
                f"   状态: {_clean_text(cur.get('status'), 'unknown')}"
                f" | 等级: {_clean_text(cur.get('severity'), 'unknown')}"
            )
            link = _clean_text(cur.get("link"), "")
            if link:
                lines.append(f"   链接: {link}")
            continue

        prev = prev_events[event_id]
        prev_status = _clean_text(prev.get("status"), "unknown")
        cur_status = _clean_text(cur.get("status"), "unknown")
        if prev_status != cur_status:
            lines.append(f"🔄 事件更新: {_clean_text(cur.get('title'), '未命名事件')}")
            lines.append(f"   状态: {prev_status} → {cur_status}")
        else:
            unchanged_events += 1

    for event_id, prev in prev_events.items():
        if event_id not in cur_events:
            lines.append(f"✅ 事件已结束: {_clean_text(prev.get('title'), '未命名事件')}")

    if not lines:
        return None
    return {'lines': lines, 'unchanged_events': unchanged_events}


def diff_aliyun(
    prev_details: Optional[Dict[str, Any]],
    cur_details: Optional[Dict[str, Any]],
) -> Optional[List[str]]:
    """对比两次阿里云事件快照，返回变化描述行列表；无差异返回 None。"""
    report = _aliyun_report(prev_details, cur_details)
    return report['lines'] if report else None
