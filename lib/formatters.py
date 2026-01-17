"""Message formatting utilities."""

from typing import Dict, Optional
from .status_checker import StatusChecker


def format_status_change_message(service_name: str, result: Dict) -> str:
    """Format a status change notification message."""
    indicator = result['indicator']
    description = result['description']
    service_type = result['type']
    info = result['info']

    # Get status emoji
    emoji = StatusChecker.get_emoji(indicator)

    header = "状态变化" if service_type == "statuspage" else "新动态"
    message = f"{emoji} 【{service_name}】{header}\n"
    message += f"详情: {description}\n"

    if service_type == "statuspage":
        # Add incident information if available
        data = result['data']
        incidents = data.get('incidents', [])
        if incidents:
            message += f"\n活动事件:\n"
            for incident in incidents[:3]:  # Max 3 incidents
                name = incident.get('name', '未知事件')
                status = incident.get('status', 'unknown')
                message += f"  - {name} ({status})\n"

        # Add status page URL
        page_url = data.get('page', {}).get('url', '')
        if page_url:
            message += f"\n监控页: {page_url}"
    elif service_type == "rss":
        entry = info.get('entry', {})
        link = entry.get('link')
        if link:
            message += f"\n链接: {link}"

    return message


def format_status_list(services_status: Dict[str, Dict]) -> str:
    """Format status list for /servicestatus command."""
    if not services_status:
        return "未配置任何服务订阅"

    response = "📊 当前监控的服务状态:\n\n"

    for service_name, result in services_status.items():
        if result is None:
            response += f"【{service_name}】\n"
            response += f"  ❌ 获取失败\n\n"
            continue

        indicator = result['indicator']
        description = result['description']
        service_type = result['type']

        # Get status emoji
        emoji = StatusChecker.get_emoji(indicator)

        response += f"【{service_name}】\n"
        response += f"  {emoji} {description}\n"

        if service_type == "statuspage":
            data = result['data']
            incidents = data.get('incidents', [])
            if incidents:
                response += f"  活动事件:\n"
                for incident in incidents[:2]:  # Max 2 incidents in list view
                    name = incident.get('name', '未知')
                    status = incident.get('status', 'unknown')
                    response += f"    • {name} ({status})\n"

        response += "\n"

    return response.strip()


def format_test_result(service_name: str, result: Optional[Dict]) -> str:
    """Format test command result."""
    if result is None:
        return f"未能获取到 {service_name} 的状态信息"

    # Show full status change style message for testing
    return format_status_change_message(service_name, result)
