"""消息格式化工具。"""

from typing import Dict, Optional, TypedDict, Any

from .status_checker import StatusChecker


class ServiceStatusResult(TypedDict):
    changed: bool
    data: Dict[str, Any]
    type: str
    indicator: str
    description: str
    info: Dict[str, Any]


def format_status_change_message(service_name: str, result: ServiceStatusResult) -> str:
    """格式化状态变更通知消息。"""
    indicator = result['indicator']
    description = result['description']
    service_type = result['type']
    info = result['info']

    # 获取状态表情符号
    emoji = StatusChecker.get_emoji(indicator)

    header = "状态变化" if service_type == "statuspage" else "新动态"
    message = f"{emoji} 【{service_name}】{header}\n"
    message += f"详情: {description}\n"

    if service_type == "statuspage":
        # Add incident information if available
        data = result['data'] or {}
        incidents = data.get('incidents', [])
        if incidents:
            message += f"\n活动事件:\n"
            for incident in incidents[:3]:  # 最多显示 3 个事件
                name = incident.get('name', '未知事件')
                status = incident.get('status', 'unknown')
                message += f"  - {name} ({status})\n"

        # 添加状态页 URL
        page_url = data.get('page', {}).get('url', '')
        if page_url:
            message += f"\n监控页: {page_url}"
    elif service_type == "rss":
        entry = info.get('entry', {})
        link = entry.get('link')
        if link:
            message += f"\n链接: {link}"

    return message


def format_status_list(services_status: Dict[str, Optional[ServiceStatusResult]]) -> str:
    """为 /servicestatus 命令格式化状态列表。"""
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

        # 获取状态表情符号
        emoji = StatusChecker.get_emoji(indicator)

        response += f"【{service_name}】\n"
        response += f"  {emoji} {description}\n"

        if service_type == "statuspage":
            data = result['data'] or {}
            incidents = data.get('incidents', [])
            if incidents:
                response += f"  活动事件:\n"
                for incident in incidents[:2]:  # 列表视图中最多显示 2 个事件
                    name = incident.get('name', '未知')
                    status = incident.get('status', 'unknown')
                    response += f"    • {name} ({status})\n"

        response += "\n"

    return response.strip()


def format_test_result(service_name: str, result: Optional[ServiceStatusResult]) -> str:
    """格式化测试命令结果。"""
    if result is None:
        return f"未能获取到 {service_name} 的状态信息"

    # 测试时显示完整的状态变更样式消息
    return format_status_change_message(service_name, result)
