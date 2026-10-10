"""查询管道协调（02-query-rag-spec 第 1 节，05 第 8 节）。

理解 -> 重写 -> 分解 -> 规划 -> 过滤 ->
混合检索 -> 重新排序 -> 证据验证 -> 上下文 -> 大型语言模型 ->
基于上下文的答案。每个步骤均按 08-prompt-spec 第 5 节的规定进行回退，
并记录在检索轨迹中。

延迟优化：
- Understanding 与 Rewrite 合并为一次结构化 LLM 调用（两者共享同一批
  上下文，规范只要求各自有独立 fallback，未要求分两次请求）。
- 多个 Sub-query 的 Filter / Hybrid Retrieval / Rerank 并发执行（06 第 9 节
  只要求「独立检索、独立记录 Trace」，串行并非契约）。
"""

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.errors import AppError, QueryStage
from app.domain.query import Intent, QueryUnderstanding, SubQuery
from app.domain.retrieval import EvidenceResult, RankedChunk
from app.ingestion.metadata import normalize_version
from app.llm.interface import LLM
from app.llm.parsing import generate_json
from app.llm.prompts.loader import PromptLoader
from app.llm.schemas import (
    QueryDecompositionOutput,
    QueryRewriteOutput,
    QueryUnderstandingOutput,
    QueryUnderstandingRewriteOutput,
)
from app.retrieval.context.builder import ContextBuilder
from app.retrieval.evidence import EvidenceChecker
from app.retrieval.filters import build_metadata_filter
from app.retrieval.hybrid import HybridResult, HybridRetriever
from app.retrieval.planner import RetrievalStrategy, plan
from app.retrieval.rerank import RerankService
from app.storage.postgres.repositories import (
    ChunkRepository,
    ConversationRepository,
    DocumentRepository,
    QueryTraceRepository,
)
from app.tracing.query_trace import QueryTraceBuilder

logger = logging.getLogger(__name__)


@dataclass
class QueryEvent:
    event: str  # meta | delta | evidence_status | done | error
    data: dict = field(default_factory=dict)


class QueryService:
    def __init__(
        self,
        settings: Settings,
        llm: LLM,
        prompts: PromptLoader,
        session_factory: async_sessionmaker[AsyncSession],
        hybrid: HybridRetriever,
        rerank_service: RerankService,
        evidence_checker: EvidenceChecker,
        context_builder: ContextBuilder,
    ) -> None:
        self._settings = settings
        self._llm = llm
        self._prompts = prompts
        self._session_factory = session_factory
        self._hybrid = hybrid
        self._rerank = rerank_service
        self._evidence = evidence_checker
        self._context = context_builder

    async def ask(
        self,
        knowledge_base_id: str,
        query: str,
        conversation_id: str | None = None,
    ) -> AsyncIterator[QueryEvent]:
        started = time.monotonic()
        answer_id = str(uuid.uuid4())
        trace = QueryTraceBuilder(
            knowledge_base_id=knowledge_base_id,
            answer_id=answer_id,
            raw_query=query,
        )
        answer_parts: list[str] = []

        try:
            conversation_id, conversation_context, known = await self._conversation_setup(
                knowledge_base_id, query, conversation_id
            )
            trace.conversation_id = conversation_id

            rewritten, understanding = await self._understand_and_rewrite(
                query, conversation_context, known, trace
            )
            trace.rewritten_query = rewritten
            trace.intent = understanding.intent.value
            trace.product = understanding.product
            trace.version = understanding.version

            strategy = plan(understanding.intent, self._settings)
            trace.retrieval_strategy = strategy.name

            yield QueryEvent(
                event="meta",
                data={
                    "conversation_id": conversation_id,
                    "answer_id": answer_id,
                    "intent": understanding.intent.value,
                    "product": understanding.product,
                    "version": understanding.version,
                    "retrieval_strategy": strategy.name,
                },
            )

            if not strategy.needs_rag:
                async for event in self._stream_general(
                    query, conversation_context, trace, answer_parts
                ):
                    yield event
            else:
                async for event in self._rag_pipeline(
                    knowledge_base_id,
                    query,
                    understanding,
                    strategy,
                    conversation_context,
                    trace,
                    answer_parts,
                ):
                    yield event

            trace.final_answer = "".join(answer_parts)
            trace.finish_stages()
            trace.latency_ms = int((time.monotonic() - started) * 1000)
            await self._persist(conversation_id, answer_id, trace)

            yield QueryEvent(
                event="done",
                data={
                    "answer_id": answer_id,
                    "context_token_count": trace.context_token_count,
                },
            )

        except AppError as exc:
            trace.error_stage = exc.stage
            trace.finish_stages()
            trace.latency_ms = int((time.monotonic() - started) * 1000)
            await self._save_trace(trace)
            yield QueryEvent(
                event="error",
                data={"error": {"code": exc.code, "stage": exc.stage, "message": exc.message}},
            )
        except Exception:  # unclassified: still never a bare RAG_ERROR
            stage = trace.current_stage or QueryStage.LLM_GENERATION.value
            trace.error_stage = stage
            trace.finish_stages()
            trace.latency_ms = int((time.monotonic() - started) * 1000)
            logger.exception("query failed at stage %s", stage)
            await self._save_trace(trace)
            # 对外只给分类码与阶段；异常原文可能含上游响应体 / SQL 片段 /
            # 文件路径，只写日志，绝不推给客户端（SSE 无法靠中间件兜底）。
            yield QueryEvent(
                event="error",
                data={
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "stage": stage,
                        "message": "internal error while processing the query",
                    }
                },
            )

    async def _rag_pipeline(
        self,
        knowledge_base_id: str,
        query: str,
        understanding: QueryUnderstanding,
        strategy: RetrievalStrategy,
        conversation_context: str,
        trace: QueryTraceBuilder,
        answer_parts: list[str],
    ) -> AsyncIterator[QueryEvent]:
        rewritten = trace.rewritten_query or query

        sub_queries = await self._decompose(rewritten, understanding, strategy, trace)
        trace.sub_queries = [
            {"id": sq.id, "query": sq.query, "product": sq.product, "version": sq.version}
            for sq in sub_queries
        ]

        # One metadata-filter trace entry per sub-query, built before retrieval.
        trace.start_stage(QueryStage.METADATA_FILTER.value)
        planned: list[tuple[SubQuery, object]] = []
        for sq in sub_queries:
            filters = build_metadata_filter(knowledge_base_id, understanding, sq)
            trace.metadata_filters.append(
                {
                    "sub_query_id": sq.id,
                    "knowledge_base_id": filters.knowledge_base_id,
                    "product": filters.product,
                    "version": filters.version,
                }
            )
            planned.append((sq, filters))

        # Sub-queries are independent (06 section 9): retrieve them concurrently.
        trace.start_stage(QueryStage.VECTOR_RETRIEVAL.value)
        retrieval_results = await asyncio.gather(
            *(
                self._hybrid.retrieve(sq.query, filters, strategy)
                for sq, filters in planned
            ),
            return_exceptions=True,
        )
        for (sq, _filters), result in zip(planned, retrieval_results, strict=True):
            if isinstance(result, BaseException):
                # HybridRetriever only raises when both paths fail
                # (RETRIEVAL_UNAVAILABLE); that must fail the whole request.
                raise result
            self._record_retrieval(trace, sq.id, result)

        # Load every sub-query's candidates in a single chunk query, then
        # rerank the sub-queries concurrently.
        all_candidate_ids = [
            cid
            for result in retrieval_results
            for cid, _score in result.candidates  # type: ignore[union-attr]
        ]
        rows_by_id = await self._rerank.load_rows(all_candidate_ids)

        trace.start_stage(QueryStage.RERANKING.value)
        ranked_pairs = await self._rerank.rank_many(
            self._rerank_batches(planned, retrieval_results),
            rows_by_id,
        )

        ranked_all: list[RankedChunk] = []
        for sq_id, outcome in ranked_pairs:
            trace.reranker_fallback = trace.reranker_fallback or outcome.fallback
            trace.record_reranked(sq_id, outcome.chunks)
            ranked_all.extend(outcome.chunks)
        # Restore deterministic order across sub-queries (gather preserves
        # input order, but extend order should match sub-query declaration).
        ranked_all.sort(key=lambda c: c.sub_query_id or "")

        trace.start_stage(QueryStage.EVIDENCE_CHECK.value)
        evidence = await self._evidence.check(rewritten, ranked_all)
        trace.record_evidence(evidence)
        yield QueryEvent(event="evidence_status", data={"status": evidence.status.value})

        trace.start_stage(QueryStage.CONTEXT_BUILDING.value)
        built = self._context.build(
            ranked_all,
            version_specified=understanding.version is not None,
        )
        trace.record_selected(built.chunks)
        trace.context_token_count = built.token_count

        async for event in self._stream_answer(
            query, built.text, conversation_context, evidence, trace, answer_parts
        ):
            yield event

    @staticmethod
    def _rerank_batches(
        planned: list[tuple[SubQuery, object]],
        retrieval_results: list[HybridResult],
    ) -> list[tuple[str, str, list[tuple[str, float]]]]:
        """Sub-query rerank inputs with cross-sub-query duplicate removal.

        Candidates are deduped globally (keeping the best RRF score) so a
        chunk recalled by several sub-queries is sent to the reranker once
        instead of N times. Each sub-query still gets its own request, so the
        per-sub-query Trace grouping in 06 section 9 is preserved.
        """
        seen: dict[str, float] = {}
        batches: list[tuple[str, str, list[tuple[str, float]]]] = []
        for (sq, _filters), result in zip(planned, retrieval_results, strict=True):
            unique: list[tuple[str, float]] = []
            for cid, score in result.candidates:
                best = seen.get(cid)
                if best is not None and best >= score:
                    continue
                seen[cid] = score
                unique.append((cid, score))
            batches.append((sq.id, sq.query, unique))
        return batches

    @staticmethod
    def _record_retrieval(
        trace: QueryTraceBuilder, sub_query_id: str, retrieval: HybridResult
    ) -> None:
        degraded = []
        if retrieval.vector_degraded:
            degraded.append(QueryStage.VECTOR_RETRIEVAL.value)
        if retrieval.keyword_degraded:
            degraded.append(QueryStage.KEYWORD_RETRIEVAL.value)
        trace.record_retrieval(
            sub_query_id,
            retrieval.vector_hits,
            retrieval.keyword_hits,
            retrieval.candidates,
            degraded,
        )

    async def _conversation_setup(
        self,
        knowledge_base_id: str,
        query: str,
        conversation_id: str | None,
    ) -> tuple[str, str, list[dict]]:
        async with self._session_factory() as session:
            conversations = ConversationRepository(session)
            if conversation_id is None:
                conversation = await conversations.create(knowledge_base_id)
                conversation_id = str(conversation.id)
                history = []
            else:
                history = await conversations.recent_messages(conversation_id)
            await conversations.add_message(conversation_id, "USER", query)
            known = await DocumentRepository(session).distinct_product_versions(knowledge_base_id)
            await session.commit()

        lines = []
        for row in history:
            speaker = "用户" if row.role == "USER" else "助手"
            lines.append(f"{speaker}: {row.content}")
        return conversation_id, "\n".join(lines) or "（无）", known

    async def _understand_and_rewrite(
        self,
        query: str,
        conversation_context: str,
        known: list[dict],
        trace: QueryTraceBuilder,
    ) -> tuple[str, QueryUnderstanding]:
        """Merged Understanding + Rewrite (one structured LLM call).

        The two stages share the same inputs (raw query, conversation, known
        products/versions); fusing them removes one round trip without losing
        any contract. Fallbacks still follow 08 section 5 independently:
        understanding -> conservative default, rewrite -> raw query.
        """
        trace.start_stage(QueryStage.QUERY_UNDERSTANDING.value)
        template = await self._prompts.get("query_understanding_rewrite")
        trace.record_prompt(template)
        rendered = PromptLoader.render(
            template,
            {
                "raw_query": query,
                "conversation_context": conversation_context,
                "known_products": ", ".join(sorted({k["product"] for k in known if k["product"]})) or "（空）",
                "known_versions": "\n".join(
                    f"{k['product']} {k['version']}" for k in known if k["product"]
                ) or "（空）",
            },
        )
        try:
            output = await generate_json(
                self._llm,
                [{"role": "system", "content": rendered}],
                QueryUnderstandingRewriteOutput,
                QueryStage.QUERY_UNDERSTANDING,
            )
            understanding = QueryUnderstanding(
                intent=output.intent,
                knowledge_required=output.knowledge_required,
                product=output.product,
                version=normalize_version(output.version),
                entities=output.entities,
                constraints=output.constraints,
            )
            rewritten = output.rewritten_query or query
        except AppError:
            # 08 section 5: conservative default, never guess product/version.
            trace.record_fallback(QueryStage.QUERY_UNDERSTANDING.value)
            trace.record_fallback(QueryStage.QUERY_REWRITE.value)
            return query, QueryUnderstanding(intent=Intent.EXACT_QA, knowledge_required=True)
        return rewritten, understanding

    async def _understand(
        self,
        query: str,
        conversation_context: str,
        known: list[dict],
        trace: QueryTraceBuilder,
    ) -> QueryUnderstanding:
        """Standalone understanding, retained for callers that need it in
        isolation (evaluation replay / debugging)."""
        trace.start_stage(QueryStage.QUERY_UNDERSTANDING.value)
        template = await self._prompts.get("query_understanding")
        trace.record_prompt(template)
        rendered = PromptLoader.render(
            template,
            {
                "raw_query": query,
                "conversation_context": conversation_context,
                "known_products": ", ".join(sorted({k["product"] for k in known if k["product"]})) or "（空）",
                "known_versions": "\n".join(
                    f"{k['product']} {k['version']}" for k in known if k["product"]
                ) or "（空）",
            },
        )
        try:
            output = await generate_json(
                self._llm,
                [{"role": "system", "content": rendered}],
                QueryUnderstandingOutput,
                QueryStage.QUERY_UNDERSTANDING,
            )
            return QueryUnderstanding(
                intent=output.intent,
                knowledge_required=output.knowledge_required,
                product=output.product,
                version=normalize_version(output.version),
                entities=output.entities,
                constraints=output.constraints,
            )
        except AppError:
            # 08 section 5: conservative default, never guess product/version
            trace.record_fallback(QueryStage.QUERY_UNDERSTANDING.value)
            return QueryUnderstanding(intent=Intent.EXACT_QA, knowledge_required=True)

    async def _rewrite(
        self,
        query: str,
        understanding: QueryUnderstanding,
        conversation_context: str,
        trace: QueryTraceBuilder,
    ) -> str:
        """Standalone rewrite, retained for callers that need it in isolation."""
        trace.start_stage(QueryStage.QUERY_REWRITE.value)
        template = await self._prompts.get("query_rewrite")
        trace.record_prompt(template)
        rendered = PromptLoader.render(
            template,
            {
                "raw_query": query,
                "conversation_context": conversation_context,
                "product": understanding.product or "（未识别）",
                "version": understanding.version or "（未指定）",
                "entities": ", ".join(understanding.entities) or "（无）",
            },
        )
        try:
            output = await generate_json(
                self._llm,
                [{"role": "system", "content": rendered}],
                QueryRewriteOutput,
                QueryStage.QUERY_REWRITE,
            )
            return output.rewritten_query or query
        except AppError:
            trace.record_fallback(QueryStage.QUERY_REWRITE.value)
            return query

    async def _decompose(
        self,
        rewritten: str,
        understanding: QueryUnderstanding,
        strategy: RetrievalStrategy,
        trace: QueryTraceBuilder,
    ) -> list[SubQuery]:
        if not strategy.decompose:
            return [
                SubQuery(
                    id="A",
                    query=rewritten,
                    product=understanding.product,
                    version=understanding.version,
                )
            ]
        trace.start_stage(QueryStage.QUERY_DECOMPOSITION.value)
        template = await self._prompts.get("query_decomposition")
        trace.record_prompt(template)
        rendered = PromptLoader.render(
            template,
            {
                "rewritten_query": rewritten,
                "intent": understanding.intent.value,
                "max_sub_queries": str(self._settings.max_sub_queries),
            },
        )
        try:
            output = await generate_json(
                self._llm,
                [{"role": "system", "content": rendered}],
                QueryDecompositionOutput,
                QueryStage.QUERY_DECOMPOSITION,
            )
            sub_queries = [
                SubQuery(id=item.id, query=item.query, product=item.product, version=item.version)
                for item in output.sub_queries[: self._settings.max_sub_queries]
            ]
            return sub_queries or [
                SubQuery(id="A", query=rewritten, product=understanding.product, version=understanding.version)
            ]
        except AppError:
            trace.record_fallback(QueryStage.QUERY_DECOMPOSITION.value)
            return [
                SubQuery(id="A", query=rewritten, product=understanding.product, version=understanding.version)
            ]

    async def _stream_answer(
        self,
        query: str,
        context: str,
        conversation_context: str,
        evidence: EvidenceResult,
        trace: QueryTraceBuilder,
        answer_parts: list[str],
    ) -> AsyncIterator[QueryEvent]:
        trace.start_stage(QueryStage.LLM_GENERATION.value)
        template = await self._prompts.get("answer_generation")
        trace.record_prompt(template)
        rendered = PromptLoader.render(
            template,
            {
                "query": query,
                "context": context or "（无可用证据）",
                "conversation_context": conversation_context,
                "evidence_status": evidence.status.value,
            },
        )
        async for token in self._llm.stream([{"role": "system", "content": rendered}]):
            answer_parts.append(token)
            yield QueryEvent(event="delta", data={"text": token})

    async def _stream_general(
        self,
        query: str,
        conversation_context: str,
        trace: QueryTraceBuilder,
        answer_parts: list[str],
    ) -> AsyncIterator[QueryEvent]:
        trace.start_stage(QueryStage.LLM_GENERATION.value)
        template = await self._prompts.get("general_answer")
        trace.record_prompt(template)
        rendered = PromptLoader.render(
            template,
            {"query": query, "conversation_context": conversation_context},
        )
        async for token in self._llm.stream([{"role": "system", "content": rendered}]):
            answer_parts.append(token)
            yield QueryEvent(event="delta", data={"text": token})

    async def _persist(
        self,
        conversation_id: str,
        answer_id: str,
        trace: QueryTraceBuilder,
    ) -> None:
        async with self._session_factory() as session:
            await ConversationRepository(session).add_message(
                conversation_id, "ASSISTANT", trace.final_answer or "", answer_id
            )
            await QueryTraceRepository(session).create(trace.to_row())
            await session.commit()

    async def _save_trace(self, trace: QueryTraceBuilder) -> None:
        try:
            async with self._session_factory() as session:
                await QueryTraceRepository(session).create(trace.to_row())
                await session.commit()
        except Exception:
            # tracing must never break the request path, but it must be visible
            logger.exception("failed to persist query trace for answer %s", trace.answer_id)

    async def get_answer_evidence(self, answer_id: str) -> dict:
        """On-demand evidence for an answer (05-api-spec section 9).

        Only SUPPORTED / PARTIALLY_SUPPORTED answers expose evidence.
        """
        async with self._session_factory() as session:
            trace = await QueryTraceRepository(session).get_by_answer(answer_id)
            if trace is None:
                raise AppError(
                    code="ANSWER_NOT_FOUND",
                    message=f"answer {answer_id} not found",
                    http_status=404,
                )
            if (trace.evidence_status or "") not in ("SUPPORTED", "PARTIALLY_SUPPORTED"):
                return {"answer_id": answer_id, "evidence": []}

            selected = trace.selected_chunks or []
            chunk_ids = [c["chunk_id"] for c in selected]
            chunk_rows = {str(r.id): r for r in await ChunkRepository(session).get_many(chunk_ids)}
            doc_ids = {c["document_id"] for c in selected}
            doc_rows = await DocumentRepository(session).get_many(list(doc_ids))
            doc_titles = {str(d.id): d.title for d in doc_rows}

        evidence = []
        for item in selected:
            row = chunk_rows.get(item["chunk_id"])
            evidence.append(
                {
                    "document_id": item["document_id"],
                    "document_title": doc_titles.get(item["document_id"]),
                    "chunk_id": item["chunk_id"],
                    "product": item.get("product"),
                    "version": item.get("version"),
                    "heading_path": item.get("heading_path"),
                    "line_start": item.get("line_start"),
                    "line_end": item.get("line_end"),
                    "excerpt": (row.raw_content or row.text)[:500] if row else None,
                }
            )
        return {"answer_id": answer_id, "evidence": evidence}
