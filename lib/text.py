"""公共文本处理工具。"""

import html
import re
from datetime import datetime, timezone
from typing import Any


def clean_text(value: Any, default: str = "-") -> str:
    """清理任意值为适合展示的单行文本。"""
    if value is None:
        return default
    text = str(value).strip()
    text = html.unescape(re.sub(r"\s+", " ", text))
    return text if text else default


def clean_summary(value: Any, max_len: int = 160) -> str:
    """清理富文本摘要：去 HTML 标签、压缩空白、截断到 max_len。"""
    raw = clean_text(value, default="")
    if not raw:
        return "-"
    no_tags = re.sub(r"<[^>]+>", " ", raw)
    text = clean_text(no_tags, default="-")
    if len(text) > max_len:
        return f"{text[:max_len - 3]}..."
    return text


def format_time(value: Any) -> str:
    """将 ISO 时间字符串格式化为 UTC 展示格式；解析失败时返回原文。"""
    text = clean_text(value, default="")
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
