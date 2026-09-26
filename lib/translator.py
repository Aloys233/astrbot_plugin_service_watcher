"""AI 翻译工具：将状态通知中的英文内容翻译为中文。

使用 AstrBot 标准 LLM 调用接口（context.llm_generate），提供商由用户在
WebUI 配置中选择。翻译结果按"原文 → 译文"缓存：
- prev 快照与当前数据中的相同原文必然得到相同译文，保证 diff 判定一致
- 未变化的文本只在首次通知时翻译一次，之后全部走缓存
"""

import asyncio
import copy
import re
from typing import Any, Dict, List, Optional, Tuple

from astrbot.api import logger

# 单条翻译超时（秒）
TRANSLATE_TIMEOUT = 30
# 单次通知最多翻译的文本条数，超出部分保留原文
MAX_TEXTS_PER_BATCH = 20
# 对同一提供商的最大并发翻译请求数
MAX_CONCURRENCY = 5
# 缓存上限，超出后清空（防止长期运行内存泄漏）
CACHE_LIMIT = 500

# 含 ASCII 字母才需要翻译（纯中文/数字/符号直接跳过）
_HAS_LATIN = re.compile(r"[A-Za-z]")
# 纯 URL / 域名类文本跳过
_IS_URL_LIKE = re.compile(r"^(https?://|www\.)\S+$", re.IGNORECASE)

PROMPT_TEMPLATE = (
    "你是一个服务状态监控通知的翻译器。请将下面的英文文本翻译成简体中文。\n"
    "要求：\n"
    "1. 只输出译文本身，不要任何解释、前缀或引号。\n"
    "2. 保留专有名词（产品名、公司名）和常见技术缩写（如 CASB、CDN、API），"
    "地名缩写可保留原文并在必要时附中文（如 GRU (São Paulo)）。\n"
    "3. 语气符合状态页公告，简洁明了。\n\n"
    "原文：{text}"
)


class Translator:
    """基于 AstrBot LLM 接口的文本翻译器。"""

    def __init__(self, context, provider_id: str) -> None:
        """
        Args:
            context: Star 的 Context 实例（用于调用 llm_generate）
            provider_id: 用户选择的聊天模型提供商 ID，为空表示未配置
        """
        self.context = context
        self.provider_id = (provider_id or "").strip()
        self._cache: Dict[str, str] = {}
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

    @property
    def is_configured(self) -> bool:
        return bool(self.provider_id)

    async def _llm_translate(self, text: str) -> Optional[str]:
        """调用 LLM 翻译单条文本（限流并发），失败返回 None。"""
        async with self._semaphore:
            try:
                resp = await asyncio.wait_for(
                    self.context.llm_generate(
                        chat_provider_id=self.provider_id,
                        prompt=PROMPT_TEMPLATE.format(text=text),
                    ),
                    timeout=TRANSLATE_TIMEOUT,
                )
                result = (getattr(resp, "completion_text", "") or "").strip()
                # 去掉模型可能添加的成对引号
                if len(result) >= 2 and result[0] == result[-1] and result[0] in "\"'“”":
                    result = result[1:-1].strip()
                return result or None
            except Exception as e:
                logger.warning(f"翻译调用失败: {repr(e)}")
                return None

    async def translate(self, text: str) -> str:
        """翻译单条文本；无需翻译、缓存命中或失败时返回原文。"""
        value = (text or "").strip()
        # 剥离 HTML 标签后再翻译：节省 token，且避免 prev/cur 仅标签差异导致的误判
        value = re.sub(r"<[^>]+>", " ", value).strip()
        if not value or not _HAS_LATIN.search(value) or _IS_URL_LIKE.match(value):
            return value

        if value in self._cache:
            return self._cache[value]

        translated = await self._llm_translate(value)
        if translated:
            if len(self._cache) >= CACHE_LIMIT:
                self._cache.clear()
            self._cache[value] = translated
            return translated
        return text

    async def translate_result(self, result: Dict[str, Any]) -> None:
        """就地翻译状态结果中会展示给用户的英文文本字段。

        会对 result['info'] 和 result['previous'] 做深拷贝后再修改，
        避免污染与 KV 快照共享的引用。previous（上次快照）与当前数据
        使用同一份缓存，保证 diff 一致性。超出单批上限的文本保留原文。
        """
        if not self.is_configured or not isinstance(result, dict):
            return

        service_type = result.get('type')
        info = result.get('info')
        if not isinstance(info, dict):
            return

        result['info'] = copy.deepcopy(info)
        details = result['info'].get('details')
        if isinstance(details, dict):
            if service_type == 'rss':
                # RSS 的 details 本身就是扁平字典 {title, published, author, link, summary}
                await self._translate_fields(details, ['title', 'summary'])
            else:
                await self._translate_tree(service_type, details)

        # rss/steamstat 的 description 为英文（statuspage/aliyun/probe 已是中文），
        # 显示在通知的"当前状态"行；经缓存翻译，与 details.title 结果保持一致
        if service_type in ('rss', 'steamstat'):
            description = result.get('description')
            if isinstance(description, str) and description.strip():
                result['description'] = await self.translate(description)

        previous = result.get('previous')
        if isinstance(previous, dict):
            # 快照同样深拷贝，避免污染 KV 中可能以引用方式持有的数据
            result['previous'] = copy.deepcopy(previous)
            await self._translate_tree(service_type, result['previous'])

    async def _translate_tree(self, service_type: str, details: Dict[str, Any]) -> None:
        """翻译一棵 details 树内的展示文本（收集→批量并发→回填）。"""
        targets = self._collect_targets(service_type, details)
        if not targets:
            return

        # 去重并截断批量上限；同一原文只翻译一次
        seen: set = set()
        pending: List[str] = []
        for container, field in targets:
            value = container.get(field)
            if not isinstance(value, str) or not value.strip():
                continue
            if value in seen:
                continue
            seen.add(value)
            if len(pending) < MAX_TEXTS_PER_BATCH:
                pending.append(value)

        if not pending:
            return

        results = await asyncio.gather(
            *(self.translate(t) for t in pending), return_exceptions=True
        )
        mapping: Dict[str, str] = {}
        for text, translated in zip(pending, results):
            if isinstance(translated, Exception) or not isinstance(translated, str):
                continue  # 失败保留原文
            mapping[text] = translated

        for container, field in targets:
            value = container.get(field)
            if isinstance(value, str) and value in mapping:
                container[field] = mapping[value]

    async def _translate_fields(self, item: Dict[str, Any], fields: List[str]) -> None:
        """翻译 dict 中指定的字符串字段。"""
        for field in fields:
            value = item.get(field)
            if isinstance(value, str) and value.strip():
                item[field] = await self.translate(value)

    @staticmethod
    def _collect_targets(
        service_type: str, details: Dict[str, Any]
    ) -> List[Tuple[Dict[str, Any], str]]:
        """按服务类型收集需要翻译的 (容器, 字段) 对。"""
        targets: List[Tuple[Dict[str, Any], str]] = []
        if service_type == 'statuspage':
            for incident in details.get('incidents', []) or []:
                if isinstance(incident, dict):
                    targets.append((incident, 'title'))
                    targets.append((incident, 'summary'))
            for maintenance in details.get('maintenances', []) or []:
                if isinstance(maintenance, dict):
                    targets.append((maintenance, 'title'))
        elif service_type == 'aliyun':
            for event in details.get('events', []) or []:
                if isinstance(event, dict):
                    targets.append((event, 'title'))
        return targets
