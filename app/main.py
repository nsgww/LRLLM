"""FastAPI entry point. Assembly only, no business logic (10 section 2).

Startup validates that the configured embedding dimension matches the
Qdrant collection; a mismatch refuses to start (10 section 8).
"""

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import sqlalchemy as sa
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.agent.runner import AgentRunner
from app.api.routers import (
    agent,
    answers,
    conversations,
    documents,
    ingestion_jobs,
    knowledge_bases,
    query,
)
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import setup_logging
from app.core.startup import validate_embedding_consistency
from app.embedding.providers.openai import OpenAIEmbedding
from app.llm.factory import is_langchain_available
from app.llm.prompts.loader import PromptLoader
from app.llm.providers.openai import OpenAILLM
from app.reranker.providers.http import HttpReranker
from app.retrieval.context.builder import ContextBuilder
from app.retrieval.evidence import EvidenceChecker
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.rerank import RerankService
from app.services.conversation_service import ConversationService
from app.services.ingestion_service import IngestionService
from app.services.knowledge_base_service import KnowledgeBaseService
from app.services.query_service import QueryService
from app.services.queue import IngestionQueue
from app.storage.keyword.store import PostgresKeywordStore
from app.storage.postgres.db import dispose_engine, get_session_factory, init_engine
from app.storage.qdrant.store import QdrantVectorStore

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging()

    # 出站地址安全校验：私网 base_url 需显式放行（防 SSRF / 云元数据探测）
    host_issues = settings.outbound_host_issues()
    if host_issues:
        raise RuntimeError(
            "unsafe outbound base_url configuration:\n  - " + "\n  - ".join(host_issues)
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        init_engine(
            settings.postgres_dsn,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout,
            pool_recycle=settings.db_pool_recycle,
        )
        session_factory = get_session_factory()

        vector_store = QdrantVectorStore(
            settings.qdrant_url,
            settings.qdrant_collection,
            settings.embedding_dimension,
        )
        await vector_store.ensure_collection()
        await vector_store.validate_dimension()
        await validate_embedding_consistency(session_factory, settings)

        embedding = OpenAIEmbedding(
            model=settings.embedding_model,
            model_version=settings.embedding_model_version,
            dimension=settings.embedding_dimension,
            api_key=settings.embedding_api_key,
            base_url=settings.embedding_base_url,
            timeout=settings.embedding_timeout_seconds,
            max_attempts=settings.provider_max_attempts,
            retry_backoff=settings.provider_retry_backoff_seconds,
        )
        llm = OpenAILLM(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            timeout=settings.llm_timeout_seconds,
            max_attempts=settings.provider_max_attempts,
            retry_backoff=settings.provider_retry_backoff_seconds,
        )
        reranker = (
            HttpReranker(
                base_url=settings.reranker_base_url or "",
                model=settings.reranker_model,
                api_key=settings.reranker_api_key,
                timeout=settings.reranker_timeout_seconds,
                max_attempts=settings.provider_max_attempts,
                retry_backoff=settings.provider_retry_backoff_seconds,
            )
            if settings.reranker_provider != "none" and settings.reranker_base_url
            else None
        )

        prompts = PromptLoader(session_factory, settings.prompt_cache_ttl_seconds)
        keyword_store = PostgresKeywordStore(session_factory)
        hybrid = HybridRetriever(vector_store, keyword_store, embedding, settings)
        rerank_service = RerankService(reranker, session_factory, settings)

        app.state.session_factory = session_factory
        app.state.vector_store = vector_store
        app.state.kb_service = KnowledgeBaseService(session_factory, vector_store)
        queue = IngestionQueue(settings.redis_url, settings.redis_queue_enabled)
        app.state.ingestion_service = IngestionService(
            session_factory, vector_store, queue
        )
        app.state.conversation_service = ConversationService(session_factory)
        app.state.query_service = QueryService(
            settings=settings,
            llm=llm,
            prompts=prompts,
            session_factory=session_factory,
            hybrid=hybrid,
            rerank_service=rerank_service,
            evidence_checker=EvidenceChecker(llm, prompts),
            context_builder=ContextBuilder(settings),
        )
        # 全局查询并发闸门：单次 /v1/query 最坏触发 ~7 次外部调用，
        # 不限流会让 LLM 配额被并发请求快速烧穿。按进程内共享信号量保护。
        app.state.query_semaphore = asyncio.Semaphore(
            max(1, settings.query_max_concurrency)
        )

        # Agent（自主工具调用）路径。langchain 为可选依赖：未安装时
        # runner 仍然构造（构造函数不触碰 langchain），但 runner_available
        # 为 False，/v1/agent 返回 503 且提示安装方式。/v1/query 完全不受影响。
        app.state.agent_runner = AgentRunner(
            settings=settings,
            session_factory=session_factory,
            hybrid=hybrid,
            rerank_service=rerank_service,
        )
        app.state.agent_runner_available = is_langchain_available()
        # Agent 与 /v1/query 分开限流：Agent 单请求外部调用数远高于固定管道，
        # 共享闸门会互相拖累。容量默认取 query 并发的一半（下限 1）。
        app.state.agent_semaphore = asyncio.Semaphore(
            max(1, settings.query_max_concurrency // 2)
        )
        if settings.agent_enabled and not app.state.agent_runner_available:
            logger.warning(
                "agent capability enabled but langchain is not installed; "
                "/v1/agent will return 503. Install with: "
                "pip install 'langchain-core>=0.3' 'langchain-openai>=0.2'"
            )
        try:
            yield
        finally:
            await queue.aclose()
            await llm.aclose()
            await embedding.aclose()
            if reranker is not None:
                await reranker.aclose()
            await vector_store.aclose()
            await dispose_engine()

    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request.state.request_id = f"req_{uuid.uuid4().hex[:16]}"
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content={
                "error": {
                    "code": exc.code,
                    "stage": exc.stage,
                    "message": exc.message,
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        """兜底：任何未分类异常都不得把原文回给客户端。

        `str(exc)` 常带 SQLAlchemy/asyncpg 语句片段、上游响应体或文件路径，
        属于信息泄露。细节只进日志，响应给出固定文案 + request_id 便于对账。
        """
        request_id = getattr(request.state, "request_id", None)
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "stage": None,
                    "message": "internal server error",
                    "request_id": request_id,
                }
            },
        )

    for module in (
        knowledge_bases,
        documents,
        ingestion_jobs,
        query,
        agent,
        answers,
        conversations,
    ):
        app.include_router(module.router, prefix=settings.api_prefix)

    @app.get("/health")
    async def health() -> dict:
        """Liveness + dependency readiness.

        Probes PostgreSQL and Qdrant so an orchestrator can distinguish a
        live-but-broken instance from a healthy one. Returns 503 when a
        dependency is unreachable.
        """
        checks: dict[str, str] = {}
        ok = True

        try:
            async with app.state.session_factory() as session:
                await session.execute(sa.text("SELECT 1"))
            checks["postgres"] = "ok"
        except Exception:  # noqa: BLE001 - any failure means the probe failed
            checks["postgres"] = "error"
            ok = False

        try:
            await app.state.vector_store.health()
            checks["qdrant"] = "ok"
        except Exception:  # noqa: BLE001 - any failure means the probe failed
            checks["qdrant"] = "error"
            ok = False

        payload = {"status": "ok" if ok else "degraded", "checks": checks}
        if not ok:
            return JSONResponse(status_code=503, content=payload)
        return payload

    return app


app = create_app()
