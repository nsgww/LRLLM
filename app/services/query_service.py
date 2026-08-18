"""Query pipeline orchestration (02-query-rag-spec section 1, 05 section 8).

Understanding -> Rewrite -> Decomposition -> Planning -> Filters ->
Hybrid Retrieval -> Rerank -> Evidence Check -> Context -> LLM ->
Grounded Answer. Every step falls back per 08-prompt-spec section 5
and is recorded in the Retrieval Trace.
"""

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
)
from app.retrieval.context.builder import ContextBuilder
from app.retrieval.evidence import EvidenceChecker
from app.retrieval.filters import build_metadata_filter
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.planner import RetrievalStrategy, plan
from app.retrieval.rerank import RerankService
from app.storage.postgres.repositories import (
    ConversationRepository,
    DocumentRepository,
    QueryTraceRepository,
)
from app.tracing.query_trace import QueryTraceBuilder


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

            understanding = await self._understand(query, conversation_context, known, trace)
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
            trace.latency_ms = int((time.monotonic() - started) * 1000)
            await self._save_trace(trace)
            yield QueryEvent(
                event="error",
                data={"error": {"code": exc.code, "stage": exc.stage, "message": exc.message}},
            )
        except Exception as exc:  # unclassified: still never a bare RAG_ERROR
            trace.error_stage = QueryStage.LLM_GENERATION.value
            trace.latency_ms = int((time.monotonic() - started) * 1000)
            await self._save_trace(trace)
            yield QueryEvent(
                event="error",
                data={
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "stage": QueryStage.LLM_GENERATION.value,
                        "message": str(exc),
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
        rewritten = await self._rewrite(query, understanding, conversation_context, trace)
        trace.rewritten_query = rewritten

        sub_queries = await self._decompose(rewritten, understanding, strategy, trace)
        trace.sub_queries = [
            {"id": sq.id, "query": sq.query, "product": sq.product, "version": sq.version}
            for sq in sub_queries
        ]

        ranked_all: list[RankedChunk] = []
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
            retrieval = await self._hybrid.retrieve(sq.query, filters, strategy)
            degraded = []
            if retrieval.vector_degraded:
                degraded.append(QueryStage.VECTOR_RETRIEVAL.value)
            if retrieval.keyword_degraded:
                degraded.append(QueryStage.KEYWORD_RETRIEVAL.value)
            trace.record_retrieval(
                sq.id,
                retrieval.vector_hits,
                retrieval.keyword_hits,
                retrieval.candidates,
                degraded,
            )
            outcome = await self._rerank.rerank(sq.query, retrieval.candidates, sub_query_id=sq.id)
            trace.reranker_fallback = trace.reranker_fallback or outcome.fallback
            trace.record_reranked(sq.id, outcome.chunks)
            ranked_all.extend(outcome.chunks)

        evidence = await self._evidence.check(rewritten, ranked_all)
        trace.record_evidence(evidence)
        yield QueryEvent(event="evidence_status", data={"status": evidence.status.value})

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

    async def _understand(
        self,
        query: str,
        conversation_context: str,
        known: list[dict],
        trace: QueryTraceBuilder,
    ) -> QueryUnderstanding:
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
            pass  # tracing must never break the request path
