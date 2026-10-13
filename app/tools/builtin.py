"""内置工具实现：知识库检索 / 元数据查询 / 直接回答。

三个工具构成最小可用集（Agent 自主决策的落地手段）：

- ``knowledge_base_search`` 走既有 HybridRetriever（向量 + 关键词 + RRF），
  Agent 可多次调用、每次换查询词或 product/version 过滤，实现「先粗后细」
  的迭代检索——这正是固定管道做不到的自主性。
- ``list_knowledge_base_documents`` 让 Agent 先摸清知识库里有什么
  （文档标题、product、version、状态），再决定检索哪些范围。
- ``answer_directly`` 是收尾信号：Agent 判断无需（或无法）检索时直接回答，
  避免在知识库无相关内容时空转。

所有工具都通过 ``build_tools(knowledge_base_id=...)`` 捕获 KB 作用域，
LLM 无法指定知识库，越权在结构上不可能（见 contracts.py 的安全约束）。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.domain.query import QueryUnderstanding, SubQuery
from app.domain.retrieval import RankedChunk
from app.retrieval.filters import build_metadata_filter
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.planner import RetrievalStrategy
from app.retrieval.rerank import RerankService
from app.storage.postgres.repositories import DocumentRepository
from app.tools.contracts import ERROR_PREFIX, ToolSpec

logger = logging.getLogger(__name__)

# 检索工具固定使用的策略名（与 planner 的 hybrid_rerank 对齐）
_SEARCH_STRATEGY = "hybrid_rerank"


def _strategy(settings: Settings, top_k_vector: int, top_k_keyword: int) -> RetrievalStrategy:
    return RetrievalStrategy(
        name=_SEARCH_STRATEGY,
        top_k_vector=top_k_vector,
        top_k_keyword=top_k_keyword,
    )


def _format_chunks(chunks: list[RankedChunk]) -> str:
    """把检索结果渲染成给 LLM 读的文本。

    刻意**不**包含 chunk_id / 内部 score 之外的标识符拼接技巧，只保留
    人类可读的标题路径、行号与正文，让 LLM 能引用来源。score 保留用于
    让模型判断相关性高低。
    """
    if not chunks:
        return "没有检索到相关内容。"
    blocks: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        location = chunk.heading_path or "(无标题)"
        meta = f"[{index}] {location} (行 {chunk.line_start}-{chunk.line_end}"
        if chunk.product:
            meta += f", 产品 {chunk.product}"
        if chunk.version:
            meta += f", 版本 {chunk.version}"
        meta += f", 相关度 {chunk.score:.4f})"
        # 优先用父块全文（04 节 17.1）：子块命中但父块提供完整上下文
        body = chunk.parent_content or chunk.raw_content or chunk.text
        blocks.append(f"{meta}\n{body}")
    return "\n\n---\n\n".join(blocks)


async def _search(
    *,
    knowledge_base_id: str,
    hybrid: HybridRetriever,
    rerank: RerankService,
    settings: Settings,
    top_k: int,
    query: str,
    product: str | None = None,
    version: str | None = None,
) -> str:
    """执行一次混合检索 + 重排，返回可读文本。"""
    # 构造理解对象：product/version 来自 LLM 显式入参；KB 来自闭包。
    understanding = QueryUnderstanding(
        intent=_intent_for_tool(),
        knowledge_required=True,
        product=product,
        version=version,
    )
    sub_query = SubQuery(id="agent", query=query, product=product, version=version)
    filters = build_metadata_filter(
        knowledge_base_id, understanding, sub_query, include_wiki=settings.wiki_in_retrieval
    )
    strategy = _strategy(settings, settings.top_k_vector, settings.top_k_keyword)

    result = await hybrid.retrieve(query, filters, strategy)
    rows_by_id = await rerank.load_rows([cid for cid, _ in result.candidates])
    outcome = await rerank.rank(query, result.candidates, rows_by_id, sub_query_id="agent")

    if outcome.fallback:
        logger.info("agent search used RRF fallback (reranker unavailable/failed)")
    return _format_chunks(outcome.chunks[:top_k])


def _intent_for_tool() -> Any:
    """工具检索不参与 intent 路由，固定用 EXACT_QA 以复用 hybrid_rerank。

    （planner.plan 对 EXACT_QA 返回 hybrid_rerank，与工具约定一致。）
    """
    from app.domain.query import Intent

    return Intent.EXACT_QA


async def _list_documents(
    *,
    knowledge_base_id: str,
    session_factory: async_sessionmaker[AsyncSession],
) -> str:
    """列出知识库内的文档概览（标题 / 产品 / 版本 / 状态）。"""
    async with session_factory() as session:
        # DocumentRepository.list returns (rows, has_more); the agent tool only
        # needs the overview rows, not pagination state.
        rows, _has_more = await DocumentRepository(session).list(
            knowledge_base_id, limit=200
        )
    if not rows:
        return "该知识库当前没有任何文档。"
    lines: list[str] = []
    for row in rows:
        parts = [f"- {row.title}"]
        if row.product:
            parts.append(f"产品={row.product}")
        if row.version:
            parts.append(f"版本={row.version}")
        if getattr(row, "doc_class", None):
            parts.append(f"类型={row.doc_class}")
        parts.append(f"状态={row.status}")
        lines.append(" ".join(parts))
    return f"知识库共 {len(rows)} 篇文档：\n" + "\n".join(lines)


def build_tools(
    *,
    knowledge_base_id: str,
    hybrid: HybridRetriever,
    rerank: RerankService,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> list[ToolSpec]:
    """构造绑定到某个知识库的工具集。

    返回的 handler 已捕获 ``knowledge_base_id``，LLM 只能提供语义参数。
    """
    top_k = settings.agent_tool_top_k

    async def knowledge_base_search(
        query: str,
        product: str | None = None,
        version: str | None = None,
    ) -> str:
        try:
            return await _search(
                knowledge_base_id=knowledge_base_id,
                hybrid=hybrid,
                rerank=rerank,
                settings=settings,
                top_k=top_k,
                query=query,
                product=product,
                version=version,
            )
        except Exception as exc:
            logger.warning("agent tool knowledge_base_search failed", exc_info=True)
            return f"{ERROR_PREFIX} 检索失败（{type(exc).__name__}），可换用更宽泛的关键词重试。"

    async def list_knowledge_base_documents() -> str:
        try:
            return await _list_documents(
                knowledge_base_id=knowledge_base_id, session_factory=session_factory
            )
        except Exception as exc:
            logger.warning("agent tool list_knowledge_base_documents failed", exc_info=True)
            return f"{ERROR_PREFIX} 读取文档列表失败（{type(exc).__name__}）。"

    async def answer_directly(answer: str) -> str:
        # 实际回答的落地由 Agent 循环读取 final answer 完成；此工具的作用
        # 是让模型显式表达「我判断不需要检索」。回执固定，避免模型把它当
        # 成输出通道而绕开最终消息。
        return "已记录：无需检索，将直接回答。"

    return [
        ToolSpec(
            name="knowledge_base_search",
            description=(
                "在当前知识库中执行混合检索（向量 + 关键词）并返回最相关的片段。"
                "需要产品事实时必须调用；可多次调用，用不同关键词或 product/version "
                "缩小范围。禁止凭记忆回答知识库相关问题。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "检索关键词或自然语言问题",
                    },
                    "product": {
                        "type": "string",
                        "description": "可选：限定产品名，仅在用户明确提及时填写",
                    },
                    "version": {
                        "type": "string",
                        "description": "可选：限定版本号，仅在用户明确提及时填写",
                    },
                },
                "required": ["query"],
            },
            handler=knowledge_base_search,
        ),
        ToolSpec(
            name="list_knowledge_base_documents",
            description=(
                "列出知识库内所有文档的标题、产品、版本与状态。"
                "当你不确定知识库覆盖哪些产品或版本时，先调用它了解范围再检索。"
            ),
            parameters={"type": "object", "properties": {}, "required": []},
            handler=list_knowledge_base_documents,
        ),
        ToolSpec(
            name="answer_directly",
            description=(
                "当你判断无需检索知识库（如问候、澄清、能力询问，或检索多次仍无"
                "相关内容）时，用此工具声明将直接回答，然后给出最终答案。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "answer": {
                        "type": "string",
                        "description": "即将给出的答复要点",
                    }
                },
                "required": ["answer"],
            },
            handler=answer_directly,
        ),
    ]
