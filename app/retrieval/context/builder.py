"""上下文构建（02-query-rag-spec 第 15-17 节，06 第 8 节）。

- 按 chunk_id 进行去重。
- 当用户未指定版本时，按版本分组并设置每个版本的上限；
  最终上下文文本中将保留分组边界。
- 表格在最终上下文中使用 raw_content（规范化文本仅用于
  检索）。
- 父子切块（04 节 17.1）：命中子块时扩展为父块全文，同一父块
  的多个命中只保留排名最高的一个，正文优先顺序为
  parent_content > raw_content > text。
- 所有内容均受令牌配额限制；质量优先于数量。
- 每个片段中始终包含标题路径。
"""

from dataclasses import dataclass, field

from app.core.config import Settings
from app.domain.retrieval import RankedChunk
from app.ingestion.chunkers.token_split import TokenCounter


@dataclass
class BuiltContext:
    text: str = ""
    chunks: list[RankedChunk] = field(default_factory=list)
    token_count: int = 0


class ContextBuilder:
    def __init__(self, settings: Settings, counter: TokenCounter | None = None) -> None:
        self._settings = settings
        self._counter = counter or TokenCounter()

    def build(
        self,
        ranked: list[RankedChunk],
        version_specified: bool,
    ) -> BuiltContext:
        chunks = _dedup(ranked)
        if not version_specified:
            chunks = _apply_version_caps(chunks, self._settings.per_version_cap)
        expand = self._settings.context_expand_to_parent
        if expand:
            chunks = _collapse_to_parents(chunks)

        context = BuiltContext()
        budget = self._settings.context_token_budget
        selected: list[RankedChunk] = []
        for chunk in chunks:
            cost = self._counter.count(_body(chunk, expand))
            if context.token_count + cost > budget:
                continue
            selected.append(chunk)
            context.token_count += cost

        context.chunks = selected
        context.text = _format(selected, version_specified, expand)
        return context


def _dedup(ranked: list[RankedChunk]) -> list[RankedChunk]:
    seen: set[str] = set()
    result = []
    for chunk in ranked:
        if chunk.chunk_id in seen:
            continue
        seen.add(chunk.chunk_id)
        result.append(chunk)
    return result


def _body(chunk: RankedChunk, expand_to_parent: bool = True) -> str:
    """Context 正文：展开开启时父块全文优先，其次表格等原始内容，
    最后规范化文本。"""
    if expand_to_parent:
        return chunk.parent_content or chunk.raw_content or chunk.text
    return chunk.raw_content or chunk.text


def _collapse_to_parents(chunks: list[RankedChunk]) -> list[RankedChunk]:
    """同一父块的多个命中子块只保留排名最高的一个。

    父块全文可能远大于子块，重复注入既浪费预算也干扰生成；无父块
    的块（代码/表格、扩展关闭前的旧文档）按 chunk_id 原样保留。
    """
    seen: set[str] = set()
    result = []
    for chunk in chunks:
        key = (
            f"parent:{chunk.parent_chunk_id}"
            if chunk.parent_content and chunk.parent_chunk_id
            else f"chunk:{chunk.chunk_id}"
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(chunk)
    return result


def _apply_version_caps(chunks: list[RankedChunk], cap: int) -> list[RankedChunk]:
    counts: dict[tuple[str | None, str | None], int] = {}
    result = []
    for chunk in chunks:
        key = (chunk.product, chunk.version)
        if counts.get(key, 0) >= cap:
            continue
        counts[key] = counts.get(key, 0) + 1
        result.append(chunk)
    return result


def _format(
    chunks: list[RankedChunk],
    version_specified: bool,
    expand_to_parent: bool = True,
) -> str:
    groups: dict[tuple[str | None, str | None], list[RankedChunk]] = {}
    order: list[tuple[str | None, str | None]] = []
    for chunk in chunks:
        key = (chunk.product, chunk.version)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(chunk)

    multiple_groups = len(order) > 1
    parts: list[str] = []
    for key in order:
        product, version = key
        if not version_specified and multiple_groups:
            label = " ".join(p for p in (product, f"v{version}" if version else None) if p)
            parts.append(f"=== {label or 'unknown version'} ===")
        for chunk in groups[key]:
            parts.append(f"[{chunk.heading_path}]\n{_body(chunk, expand_to_parent)}")
    return "\n\n".join(parts)
