"""LLM Wiki service (11-llm-wiki-spec).

Distills grounded Q&A into versioned wiki pages, and indexes each published
revision as a *shadow document* so it participates in hybrid retrieval without
a parallel retrieval stack. Contract: distillation never blocks or fails the
main query pipeline — the auto-trigger caller catches and logs, while the
manual endpoint surfaces failures as 502.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.errors import AppError, QueryStage
from app.core.ids import assert_same_kb
from app.domain.chunk import Chunk, ChunkType
from app.domain.document import Document, DocumentStatus
from app.domain.retrieval import EvidenceStatus
from app.domain.wiki import WikiPage, WikiRevision, WikiSourceRef, WikiStatus
from app.embedding.interface import EmbeddingModel
from app.llm.interface import LLM
from app.llm.parsing import generate_json
from app.llm.prompts.loader import PromptLoader
from app.llm.schemas import WikiExtractionOutput
from app.storage.base import VectorPoint, VectorStore
from app.storage.postgres.repositories import (
    ChunkRepository,
    DocumentRepository,
    QueryTraceRepository,
    WikiPageRepository,
    WikiRevisionRepository,
)

logger = logging.getLogger(__name__)

_WIKI_PROMPT_KEY = "wiki_extraction"
_GROUNDED = (EvidenceStatus.SUPPORTED, EvidenceStatus.PARTIALLY_SUPPORTED)
_EVIDENCE_MAX_CHARS = 4000


@dataclass
class _IndexPlan:
    """Shadow-document index plan: DB half runs inside the caller's transaction,
    vector half (``_apply_vectors``) runs only *after* commit (11 §6) so a
    rolled-back transaction can never leave the old content vector-less."""

    old_chunk_ids: list[str]
    chunk_id: str
    document_id: str
    kb_id: str
    page_id: str
    slug: str
    title: str
    content: str


@dataclass
class WikiDistillResult:
    created: bool
    skipped: bool
    page_id: str | None = None
    revision_version: int | None = None
    slug: str = ""
    title: str = ""
    reason: str = ""


class WikiService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        llm: LLM,
        prompts: PromptLoader,
        vector_store: VectorStore,
        embedding: EmbeddingModel,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._llm = llm
        self._prompts = prompts
        self._vector_store = vector_store
        self._embedding = embedding
        self._settings = settings

    # ------------------------------------------------------------------ #
    # Distill: query trace -> structured entry -> versioned page + index #
    # ------------------------------------------------------------------ #
    async def distill(self, answer_id: str, kb_id: str | None = None) -> WikiDistillResult:
        if not self._settings.wiki_enabled:
            raise AppError(
                code="WIKI_DISABLED",
                message="LLM Wiki is disabled (RAG_WIKI_ENABLED=false)",
                http_status=503,
            )

        async with self._session_factory() as session:
            trace = await QueryTraceRepository(session).get_by_answer(answer_id)
            if trace is None:
                raise AppError(
                    code="ANSWER_NOT_FOUND",
                    message=f"answer {answer_id} not found",
                    http_status=404,
                )
            if kb_id:
                assert_same_kb(trace, kb_id)

            # Only grounded answers are distillable: wiki must stay traceable
            # to evidence (11 section 8.5). INSUFFICIENT / CONTRADICTED reject.
            if trace.evidence_status not in _GROUNDED:
                raise AppError(
                    code="WIKI_INSUFFICIENT_EVIDENCE",
                    message="only SUPPORTED / PARTIALLY_SUPPORTED answers can be distilled",
                    http_status=400,
                )

            final_answer = (trace.final_answer or "").strip()
            if not final_answer:
                return WikiDistillResult(created=False, skipped=True, reason="empty_answer")

            source_query = trace.raw_query
            evidence_text = _evidence_text(trace.selected_chunks)
            evidence_list = _evidence_list(trace.selected_chunks)
            real_kb = str(trace.knowledge_base_id)

            try:
                out = await self._extract(source_query, final_answer, evidence_text, "")
            except AppError as exc:
                raise self._extraction_error("wiki extraction failed", exc) from exc

            if not out.should_create or not out.slug.strip():
                return WikiDistillResult(created=False, skipped=True, reason="no_value")
            slug = _normalize_slug(out.slug)

            pages = WikiPageRepository(session)
            revisions = WikiRevisionRepository(session)
            page = await pages.get_published_by_slug(real_kb, slug)
            source = WikiSourceRef(
                answer_id=answer_id, query=source_query, evidence=evidence_list
            )

            if page is not None:
                latest = await revisions.get_latest(str(page.id))
                existing = latest.content if latest else ""
                try:
                    merged = await self._extract(
                        source_query, final_answer, evidence_text, existing
                    )
                except AppError as exc:
                    raise self._extraction_error("wiki merge failed", exc) from exc
                if not merged.should_create or not merged.content.strip():
                    return WikiDistillResult(
                        created=False, skipped=True, slug=slug, reason="no_increment"
                    )
                title = merged.title or page.title
                summary = merged.summary or page.summary
                content = merged.content
                version = await revisions.next_version(str(page.id))
                try:
                    await revisions.create(
                        WikiRevision(
                            page_id=str(page.id),
                            version=version,
                            content=content,
                            source=source,
                            change_note=f"增补自 answer {answer_id}",
                        )
                    )
                except IntegrityError as exc:
                    raise AppError(
                        code="WIKI_CONFLICT",
                        message="concurrent distill on the same page; retry",
                        http_status=409,
                    ) from exc
                await pages.touch(
                    str(page.id), title=title, summary=summary, revision_count=version
                )
                plan = await self._index_db(session, real_kb, str(page.id), slug, title, content)
                await session.commit()
                await self._apply_vectors(plan)
                return WikiDistillResult(
                    created=False,
                    skipped=False,
                    page_id=str(page.id),
                    revision_version=version,
                    slug=slug,
                    title=title,
                )

            # Brand-new page
            try:
                page_row = await pages.create(
                    WikiPage(
                        knowledge_base_id=real_kb,
                        slug=slug,
                        title=out.title or slug,
                        summary=out.summary,
                        status=WikiStatus.PUBLISHED,
                        revision_count=1,
                    )
                )
            except IntegrityError as exc:
                # 并发 distill 同 slug：唯一约束冲突收敛为 409（可重试）。
                raise AppError(
                    code="WIKI_CONFLICT",
                    message="concurrent distill created the same page; retry",
                    http_status=409,
                ) from exc
            page_id = str(page_row.id)
            await revisions.create(
                WikiRevision(
                    page_id=page_id,
                    version=1,
                    content=out.content,
                    source=source,
                    change_note="新建自问答沉淀",
                )
            )
            plan = await self._index_db(session, real_kb, page_id, slug, out.title or slug, out.content)
            await session.commit()
            await self._apply_vectors(plan)
            return WikiDistillResult(
                created=True,
                skipped=False,
                page_id=page_id,
                revision_version=1,
                slug=slug,
                title=out.title or slug,
            )

    async def _extract(
        self,
        source_query: str,
        final_answer: str,
        evidence_text: str,
        existing_content: str,
    ) -> WikiExtractionOutput:
        template = await self._prompts.get(_WIKI_PROMPT_KEY)
        rendered = PromptLoader.render(
            template,
            {
                "source_query": source_query,
                "final_answer": final_answer,
                "evidence": evidence_text,
                "existing_content": existing_content,
                "max_content_tokens": str(self._settings.wiki_max_content_tokens),
            },
        )
        return await generate_json(
            self._llm,
            [{"role": "user", "content": rendered}],
            WikiExtractionOutput,
            QueryStage.LLM_GENERATION,
        )

    # ------------------------------------------------------------------ #
    # Index a published revision as a shadow document (single chunk)      #
    # ------------------------------------------------------------------ #
    async def _index_db(
        self,
        session: AsyncSession,
        kb_id: str,
        page_id: str,
        slug: str,
        title: str,
        content: str,
    ) -> _IndexPlan:
        """DB half of shadow-document indexing (inside the caller's txn).

        Retires the previous shadow document and creates the new chunk; vector
        mutations are deferred to ``_apply_vectors`` after commit so a rolled
        back transaction can never leave the old content vector-less.
        """
        documents = DocumentRepository(session)
        chunks = ChunkRepository(session)
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        old = await documents.get_by_wiki_page(kb_id, page_id)
        old_chunk_ids: list[str] = []
        if old is not None:
            old_chunk_ids = await chunks.list_ids_by_document(str(old.id))
            await chunks.soft_delete_by_document(str(old.id))
            await documents.soft_delete(str(old.id))

        doc_row = await documents.create(
            Document(
                knowledge_base_id=kb_id,
                title=title,
                content=content.encode("utf-8"),
                content_hash=content_hash,
                source_type="wiki",
                wiki_page_id=page_id,
                doc_class="wiki",
                source=f"wiki:{slug}",
                status=DocumentStatus.READY,
                embedding_model=self._embedding.model_name,
                embedding_model_version=self._embedding.model_version,
            )
        )
        document_id = str(doc_row.id)
        chunk = Chunk(
            document_id=document_id,
            section_id=None,
            knowledge_base_id=kb_id,
            text=content,
            heading_path=title,
            line_start=1,
            line_end=content.count("\n") + 1,
            chunk_index=0,
            token_count=_estimate_tokens(content),
            content_hash=content_hash,
            chunk_type=ChunkType.TEXT,
            embedding_model=self._embedding.model_name,
            embedding_model_version=self._embedding.model_version,
        )
        chunk_id = (await chunks.bulk_create([chunk]))[0]
        return _IndexPlan(
            old_chunk_ids=old_chunk_ids,
            chunk_id=chunk_id,
            document_id=document_id,
            kb_id=kb_id,
            page_id=page_id,
            slug=slug,
            title=title,
            content=content,
        )

    async def _apply_vectors(self, plan: _IndexPlan) -> None:
        """Vector half — call only after commit. Failures are logged, not raised:
        the page is already committed; vector recall can be rebuilt later."""
        try:
            if plan.old_chunk_ids:
                await self._vector_store.delete(plan.old_chunk_ids)
            vector = (await self._embedding.embed_documents([f"{plan.title}\n{plan.content}"]))[0]
            await self._vector_store.upsert(
                [
                    VectorPoint(
                        chunk_id=plan.chunk_id,
                        vector=vector,
                        payload={
                            "knowledge_base_id": plan.kb_id,
                            "document_id": plan.document_id,
                            "section_id": None,
                            "chunk_id": plan.chunk_id,
                            "product": None,
                            "version": None,
                            "doc_class": "wiki",
                            "chunk_type": "TEXT",
                            "source_type": "wiki",
                            "wiki_page_id": plan.page_id,
                            "title": plan.title,
                            "slug": plan.slug,
                        },
                    )
                ]
            )
        except Exception:
            logger.warning(
                "wiki shadow-document vector apply failed for page %s",
                plan.page_id,
                exc_info=True,
            )

    # ------------------------------------------------------------------ #
    # Read / delete                                                       #
    # ------------------------------------------------------------------ #
    async def list_pages(
        self,
        kb_id: str,
        limit: int = 50,
        cursor=None,
    ):
        async with self._session_factory() as session:
            return await WikiPageRepository(session).list(kb_id, limit, cursor)

    async def get_page(self, page_id: str, kb_id: str | None = None):
        async with self._session_factory() as session:
            page = await WikiPageRepository(session).get(page_id)
            if page is None:
                raise AppError(
                    code="WIKI_PAGE_NOT_FOUND",
                    message=f"wiki page {page_id} not found",
                    http_status=404,
                )
            if kb_id:
                assert_same_kb(page, kb_id)
            revisions, _ = await WikiRevisionRepository(session).list_by_page(str(page.id))
            return page, revisions

    async def delete_page(self, page_id: str, kb_id: str | None = None) -> None:
        async with self._session_factory() as session:
            pages = WikiPageRepository(session)
            page = await pages.get(page_id)
            if page is None:
                raise AppError(
                    code="WIKI_PAGE_NOT_FOUND",
                    message=f"wiki page {page_id} not found",
                    http_status=404,
                )
            if kb_id:
                assert_same_kb(page, kb_id)

            documents = DocumentRepository(session)
            chunks = ChunkRepository(session)
            shadow = await documents.get_by_wiki_page(str(page.knowledge_base_id), page_id)
            orphan_chunk_ids: list[str] = []
            if shadow is not None:
                orphan_chunk_ids = await chunks.list_ids_by_document(str(shadow.id))
                await chunks.soft_delete_by_document(str(shadow.id))
                await documents.soft_delete(str(shadow.id))
            await pages.soft_delete(page_id)
            # 先 commit 后动向量（与 _index_db/_apply_vectors 同一不变量）：
            # commit 回滚时旧内容向量不受影响，避免"有行无向量"的静默不可召回。
            await session.commit()
            if orphan_chunk_ids:
                try:
                    await self._vector_store.delete(orphan_chunk_ids)
                except Exception:
                    logger.warning(
                        "wiki page %s vector cleanup failed; reconcile will retry",
                        page_id,
                        exc_info=True,
                    )

    @staticmethod
    def _extraction_error(prefix: str, exc: AppError) -> AppError:
        return AppError(
            code="WIKI_EXTRACTION_FAILED",
            message=f"{prefix}: {exc.message}",
            http_status=502,
            stage=exc.stage or QueryStage.LLM_GENERATION,
        )


def _normalize_slug(slug: str) -> str:
    return slug.strip().lower()


def _estimate_tokens(text: str) -> int:
    # Rough heuristic; wiki pages are single-chunk and this count only feeds
    # context-budget accounting. Keeps services free of ingestion imports.
    return max(1, (len(text) + 3) // 4)


def _evidence_text(selected) -> str:
    if not selected:
        return "（无）"
    try:
        text = json.dumps(selected, ensure_ascii=False)
    except TypeError:
        text = str(selected)
    return text[:_EVIDENCE_MAX_CHARS]


def _evidence_list(selected) -> list:
    if isinstance(selected, list):
        return selected
    if isinstance(selected, dict):
        return list(selected.get("chunks", []) or [])
    return []
