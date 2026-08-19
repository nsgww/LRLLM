"""FastAPI entry point. Assembly only, no business logic (10 section 2).

Startup validates that the configured embedding dimension matches the
Qdrant collection; a mismatch refuses to start (10 section 8).
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routers import (
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
from app.embedding.providers.openai import OpenAIEmbedding
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
from app.storage.keyword.store import PostgresKeywordStore
from app.storage.postgres.db import get_session_factory, init_engine
from app.storage.qdrant.store import QdrantVectorStore


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        init_engine(settings.postgres_dsn)
        session_factory = get_session_factory()

        vector_store = QdrantVectorStore(
            settings.qdrant_url,
            settings.qdrant_collection,
            settings.embedding_dimension,
        )
        await vector_store.ensure_collection()
        await vector_store.validate_dimension()

        embedding = OpenAIEmbedding(
            model=settings.embedding_model,
            model_version=settings.embedding_model_version,
            dimension=settings.embedding_dimension,
            api_key=settings.embedding_api_key,
            base_url=settings.embedding_base_url,
        )
        llm = OpenAILLM(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
        )
        reranker = (
            HttpReranker(
                base_url=settings.reranker_base_url or "",
                model=settings.reranker_model,
                api_key=settings.reranker_api_key,
            )
            if settings.reranker_provider != "none" and settings.reranker_base_url
            else None
        )

        prompts = PromptLoader(session_factory, settings.prompt_cache_ttl_seconds)
        keyword_store = PostgresKeywordStore(session_factory)
        hybrid = HybridRetriever(vector_store, keyword_store, embedding, settings)
        rerank_service = RerankService(reranker, session_factory, settings)

        app.state.session_factory = session_factory
        app.state.kb_service = KnowledgeBaseService(session_factory)
        app.state.ingestion_service = IngestionService(session_factory, vector_store)
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
        yield
        await llm.aclose()
        await embedding.aclose()
        if reranker is not None:
            await reranker.aclose()

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

    for module in (knowledge_bases, documents, ingestion_jobs, query, answers, conversations):
        app.include_router(module.router, prefix=settings.api_prefix)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
