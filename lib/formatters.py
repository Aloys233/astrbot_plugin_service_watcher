"""消息格式化工具。"""

import html
import re
from datetime import datetime, timezone
from typing import Dict, Optional, TypedDict, Any, List

from .status_checker import StatusChecker


class ServiceStatusResult(TypedDict):
    changed: bool
    data: Dict[str, Any]
    type: str
    indicator: str
    description: str
    info: Dict[str, Any]


def _service_type_label(service_type: str) -> str:
    labels = {
        "statuspage": "StatusPage",
        "rss": "RSS",
        "aliyun": "Aliyun",
        "steamstat": "Steam"
    }
    return labels.get(service_type, service_type)


def _clean_text(value: Any, default: str = "-") -> str:
    if value is None:
        return default
    text = str(value).strip()
    text = html.unescape(re.sub(r"\s+", " ", text))
    return text if text else default


def _clean_summary(value: Any, max_len: int = 160) -> str:
    raw = _clean_text(value, default="")
    if not raw:
        return "-"
    no_tags = re.sub(r"<[^>]+>", " ", raw)
    text = _clean_text(no_tags, default="-")
    if len(text) > max_len:
        return f"{text[:max_len - 3]}..."
    return text


def _format_time(value: Any) -> str:
    text = _clean_text(value, default="")
    if not text:
        return "-"

    try:
        normalized = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo:
            return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return text


def _format_statuspage_details(info: Dict[str, Any], limit: int = 3) -> List[str]:
    details = info.get("details", {}) if isinstance(info, dict) else {}
    incidents = details.get("incidents", []) if isinstance(details.get("incidents"), list) else []
    lines: List[str] = []

    page_url = _clean_text(details.get("page_url"), "")
    if page_url:
        lines.append(f"监控页: {page_url}")

    if not incidents:
        lines.append("事件: 无活跃事件")
    else:
        lines.append(f"事件: {len(incidents)} 个")
        for index, incident in enumerate(incidents[:limit], start=1):
            if not isinstance(incident, dict):
                continue
            title = _clean_text(incident.get("title"), "未知事件")
            status = _clean_text(incident.get("status"), "unknown")
            impact = _clean_text(incident.get("impact"), "unknown")
            updated_at = _format_time(incident.get("updated_at"))
            summary = _clean_summary(incident.get("summary"))
            link = _clean_text(incident.get("link"), "")

            lines.append(f"{index}. {title}")
            lines.append(f"   状态: {status} | 影响: {impact} | 更新时间: {updated_at}")
            lines.append(f"   说明: {summary}")
            if link:
                lines.append(f"   链接: {link}")

    return lines


def _format_rss_details(info: Dict[str, Any]) -> List[str]:
    details = info.get("details", {}) if isinstance(info, dict) else {}
    entry = info.get("entry", {}) if isinstance(info, dict) else {}

    title = _clean_text(details.get("title") or entry.get("title"), "新动态")
    published = _format_time(details.get("published") or entry.get("published") or entry.get("updated"))
    author = _clean_text(details.get("author") or entry.get("author"), "-")
    link = _clean_text(details.get("link") or entry.get("link"), "-")
    summary = _clean_summary(details.get("summary") or entry.get("summary") or entry.get("description"))

    return [
        f"标题: {title}",
        f"发布时间: {published}",
        f"作者: {author}",
        f"摘要: {summary}",
        f"链接: {link}",
    ]


def _format_aliyun_details(info: Dict[str, Any], limit: int = 3) -> List[str]:
    details = info.get("details", {}) if isinstance(info, dict) else {}
    events = details.get("events", []) if isinstance(details.get("events"), list) else []
    lines: List[str] = []

    if not events:
        lines.append("事件: 无活跃事件")
        return lines

    lines.append(f"事件: {len(events)} 个")
    for index, event in enumerate(events[:limit], start=1):
        if not isinstance(event, dict):
            continue
        title = _clean_text(event.get("title"), "未命名事件")
        status = _clean_text(event.get("status"), "unknown")
        severity = _clean_text(event.get("severity"), "unknown")
        started_at = _format_time(event.get("started_at"))
        updated_at = _format_time(event.get("updated_at"))
        link = _clean_text(event.get("link"), "")

        lines.append(f"{index}. {title}")
        lines.append(f"   状态: {status} | 等级: {severity}")
        lines.append(f"   开始: {started_at} | 更新: {updated_at}")
        if link:
            lines.append(f"   链接: {link}")

    return lines


def format_status_change_message(service_name: str, result: ServiceStatusResult) -> str:
    """格式化状态变更通知消息。"""
    indicator = result['indicator']
    description = result['description']
    service_type = result['type']
    info = result['info']

    emoji = StatusChecker.get_emoji(indicator)
    changed_text = "是" if result.get("changed") else "否"

    header = "状态变更通知" if service_type in {"statuspage", "aliyun"} else "订阅更新通知"
    lines = [
        f"{emoji} [{service_name}] {header}",
        f"类型: {_service_type_label(service_type)}",
        f"当前状态: {description} ({indicator})",
        f"检测到变化: {changed_text}"
    ]

    if service_type == "statuspage":
        lines.extend(_format_statuspage_details(info, limit=3))
    elif service_type == "rss":
        lines.extend(_format_rss_details(info))
    elif service_type == "aliyun":
        lines.extend(_format_aliyun_details(info, limit=3))

    return "\n".join(lines)


def format_status_list(services_status: Dict[str, Optional[ServiceStatusResult]]) -> str:
    """为 /servicestatus 命令格式化状态列表。"""
    if not services_status:
        return "未配置任何服务订阅"

    lines = [
        "📊 当前监控服务状态",
        f"服务总数: {len(services_status)}",
        ""
    ]

    for index, (service_name, result) in enumerate(services_status.items(), start=1):
        if result is None:
            lines.append(f"{index}. {service_name}")
            lines.append("   状态: ❌ 获取失败")
            lines.append("")
            continue

        if isinstance(result, dict) and result.get("error"):
            reason = _clean_text(result.get("error"), "未知错误")
            lines.append(f"{index}. {service_name}")
            lines.append(f"   状态: ❌ 获取失败（{reason}）")
            lines.append("")
            continue

        indicator = result['indicator']
        description = result['description']
        service_type = result['type']
        info = result['info']

        emoji = StatusChecker.get_emoji(indicator)
        lines.append(f"{index}. {service_name} [{_service_type_label(service_type)}]")
        lines.append(f"   状态: {emoji} {description} ({indicator})")

        if service_type == "statuspage":
            details = info.get("details", {}) if isinstance(info, dict) else {}
            incidents = details.get("incidents", []) if isinstance(details.get("incidents"), list) else []
            if incidents:
                lines.append(f"   活跃事件: {len(incidents)} 个")
                for incident in incidents[:2]:
                    if not isinstance(incident, dict):
                        continue
                    title = _clean_text(incident.get("title"), "未知事件")
                    lines.append(f"   - {title}")
            else:
                lines.append("   活跃事件: 无")

        elif service_type == "rss":
            details = info.get("details", {}) if isinstance(info, dict) else {}
            title = _clean_text(details.get("title"), description)
            published = _format_time(details.get("published"))
            lines.append(f"   最新动态: {title}")
            lines.append(f"   发布时间: {published}")

        elif service_type == "aliyun":
            details = info.get("details", {}) if isinstance(info, dict) else {}
            events = details.get("events", []) if isinstance(details.get("events"), list) else []
            if events:
                lines.append(f"   活跃事件: {len(events)} 个")
                for event in events[:2]:
                    if not isinstance(event, dict):
                        continue
                    title = _clean_text(event.get("title"), "未命名事件")
                    status = _clean_text(event.get("status"), "unknown")
                    severity = _clean_text(event.get("severity"), "unknown")
                    lines.append(f"   - {title} ({status}, {severity})")
            else:
                lines.append("   活跃事件: 无")

        lines.append("")

    return "\n".join(lines).strip()


def format_test_result(service_name: str, result: Optional[ServiceStatusResult]) -> str:
    """格式化测试命令结果。"""
    if result is None:
        return f"未能获取到 {service_name} 的状态信息"

    return f"🧪 测试结果\n{format_status_change_message(service_name, result)}"
