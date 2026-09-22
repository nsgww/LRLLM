"""Repositories. All queries must respect soft delete (deleted_at IS NULL)
and scope filters (knowledge_base_id).
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.ids import parse_uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.chunk import Chunk
from app.domain.document import Document, DocumentStatus
from app.domain.ingestion import IngestionJob, JobStatus
from app.domain.section import Section
from app.storage.postgres.orm import (
    ChunkRow,
    ConversationMessageRow,
    ConversationRow,
    DocumentRow,
    IngestionJobRow,
    KnowledgeBaseRow,
    PromptTemplateRow,
    QueryTraceRow,
    SectionRow,
)


def _apply_cursor(
    stmt,
    model,
    cursor: tuple[datetime, str] | None,
    *,
    descending: bool,
):
    """Keyset pagination on (created_at, id); ordering must match `descending`."""
    if cursor is None:
        return stmt
    created_at, last_id = cursor
    last_uuid = parse_uuid(last_id)
    if descending:
        return stmt.where(
            sa.or_(
                model.created_at < created_at,
                sa.and_(model.created_at == created_at, model.id < last_uuid),
            )
        )
    return stmt.where(
        sa.or_(
            model.created_at > created_at,
            sa.and_(model.created_at == created_at, model.id > last_uuid),
        )
    )


class KnowledgeBaseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, name: str, description: str | None) -> KnowledgeBaseRow:
        row = KnowledgeBaseRow(name=name, description=description)
        self._session.add(row)
        await self._session.flush()
        return row

    async def get(self, kb_id: str) -> KnowledgeBaseRow | None:
        stmt = sa.select(KnowledgeBaseRow).where(
            KnowledgeBaseRow.id == parse_uuid(kb_id),
            KnowledgeBaseRow.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list(
        self, limit: int = 50, cursor: tuple[datetime, str] | None = None
    ) -> tuple[list[KnowledgeBaseRow], bool]:
        stmt = (
            sa.select(KnowledgeBaseRow)
            .where(KnowledgeBaseRow.deleted_at.is_(None))
            .order_by(KnowledgeBaseRow.created_at.desc(), KnowledgeBaseRow.id.desc())
            .limit(limit + 1)
        )
        stmt = _apply_cursor(stmt, KnowledgeBaseRow, cursor, descending=True)
        rows = list((await self._session.execute(stmt)).scalars().all())
        has_more = len(rows) > limit
        return rows[:limit], has_more

    async def soft_delete(self, kb_id: str) -> None:
        await self._session.execute(
            sa.update(KnowledgeBaseRow)
            .where(KnowledgeBaseRow.id == parse_uuid(kb_id))
            .values(deleted_at=datetime.now(UTC))
        )


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, doc: Document) -> DocumentRow:
        row = DocumentRow(
            knowledge_base_id=parse_uuid(doc.knowledge_base_id),
            title=doc.title,
            doc_class=doc.doc_class,
            source=doc.source,
            product=doc.product,
            version=doc.version,
            content=doc.content,
            content_hash=doc.content_hash,
            parser_version=doc.parser_version,
            chunker_version=doc.chunker_version,
            embedding_model=doc.embedding_model,
            embedding_model_version=doc.embedding_model_version,
            processing_fingerprint=doc.processing_fingerprint,
            status=doc.status,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get(self, document_id: str) -> DocumentRow | None:
        stmt = sa.select(DocumentRow).where(
            DocumentRow.id == parse_uuid(document_id),
            DocumentRow.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_hash(self, kb_id: str, content_hash: str) -> DocumentRow | None:
        stmt = sa.select(DocumentRow).where(
            DocumentRow.knowledge_base_id == parse_uuid(kb_id),
            DocumentRow.content_hash == content_hash,
            DocumentRow.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list(
        self,
        kb_id: str,
        limit: int = 50,
        cursor: tuple[datetime, str] | None = None,
    ) -> tuple[list[DocumentRow], bool]:
        stmt = (
            sa.select(DocumentRow)
            .where(
                DocumentRow.knowledge_base_id == parse_uuid(kb_id),
                DocumentRow.deleted_at.is_(None),
            )
            .order_by(DocumentRow.created_at.desc(), DocumentRow.id.desc())
            .limit(limit + 1)
        )
        stmt = _apply_cursor(stmt, DocumentRow, cursor, descending=True)
        rows = list((await self._session.execute(stmt)).scalars().all())
        has_more = len(rows) > limit
        return rows[:limit], has_more

    async def update_status(
        self,
        document_id: str,
        status: DocumentStatus,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        await self._session.execute(
            sa.update(DocumentRow)
            .where(DocumentRow.id == parse_uuid(document_id))
            .values(
                status=status,
                error_code=error_code,
                error_message=error_message,
                updated_at=datetime.now(UTC),
            )
        )

    async def soft_delete(self, document_id: str) -> None:
        await self._session.execute(
            sa.update(DocumentRow)
            .where(DocumentRow.id == parse_uuid(document_id))
            .values(deleted_at=datetime.now(UTC))
        )

    async def soft_delete_by_kb(self, kb_id: str) -> None:
        """Cascade soft delete when a knowledge base is removed (05 section 5)."""
        await self._session.execute(
            sa.update(DocumentRow)
            .where(
                DocumentRow.knowledge_base_id == parse_uuid(kb_id),
                DocumentRow.deleted_at.is_(None),
            )
            .values(deleted_at=datetime.now(UTC))
        )

    async def list_purgeable_ids(self, limit: int = 200) -> list[str]:
        """Soft-deleted documents whose chunks are all physically gone, so the
        row (and its cascaded sections/jobs) can be purged without leaving
        Qdrant points unreferenced."""
        chunk_exists = (
            sa.select(ChunkRow.id).where(ChunkRow.document_id == DocumentRow.id).exists()
        )
        stmt = (
            sa.select(DocumentRow.id)
            .where(DocumentRow.deleted_at.is_not(None), ~chunk_exists)
            .limit(limit)
        )
        return [str(r) for r in (await self._session.execute(stmt)).scalars().all()]

    async def hard_delete_ids(self, document_ids: list[str]) -> None:
        if not document_ids:
            return
        await self._session.execute(
            sa.delete(DocumentRow).where(
                DocumentRow.id.in_([parse_uuid(i) for i in document_ids])
            )
        )

    async def get_many(self, document_ids: list[str]) -> list[DocumentRow]:
        if not document_ids:
            return []
        stmt = sa.select(DocumentRow).where(
            DocumentRow.id.in_([parse_uuid(i) for i in document_ids]),
            DocumentRow.deleted_at.is_(None),
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def distinct_embedding_versions(self) -> list[str]:
        """Indexed embedding model versions, for the startup consistency check
        (06 section 4): the query-time model must match what was indexed."""
        stmt = (
            sa.select(DocumentRow.embedding_model_version)
            .where(
                DocumentRow.deleted_at.is_(None),
                DocumentRow.embedding_model_version.is_not(None),
            )
            .distinct()
        )
        return [v for v in (await self._session.execute(stmt)).scalars().all() if v]

    async def distinct_product_versions(self, kb_id: str) -> list[dict]:
        """Known products/versions for query_understanding grounding (08 section 4.1)."""
        stmt = (
            sa.select(DocumentRow.product, DocumentRow.version)
            .where(
                DocumentRow.knowledge_base_id == parse_uuid(kb_id),
                DocumentRow.deleted_at.is_(None),
                DocumentRow.product.is_not(None),
            )
            .distinct()
        )
        rows = (await self._session.execute(stmt)).all()
        return [{"product": product, "version": version} for product, version in rows]

    async def update_metadata(
        self,
        document_id: str,
        *,
        title: str | None,
        doc_class: str | None,
        source: str | None,
        product: str | None,
        version: str | None,
    ) -> None:
        await self._session.execute(
            sa.update(DocumentRow)
            .where(DocumentRow.id == parse_uuid(document_id))
            .values(
                title=title,
                doc_class=doc_class,
                source=source,
                product=product,
                version=version,
                updated_at=datetime.now(UTC),
            )
        )

    async def update_processing(
        self,
        document_id: str,
        *,
        parser_version: str,
        chunker_version: str,
        embedding_model: str,
        embedding_model_version: str,
        processing_fingerprint: str,
    ) -> None:
        await self._session.execute(
            sa.update(DocumentRow)
            .where(DocumentRow.id == parse_uuid(document_id))
            .values(
                parser_version=parser_version,
                chunker_version=chunker_version,
                embedding_model=embedding_model,
                embedding_model_version=embedding_model_version,
                processing_fingerprint=processing_fingerprint,
                updated_at=datetime.now(UTC),
            )
        )


class SectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def bulk_create(self, sections: list[Section]) -> list[str]:
        rows = [
            SectionRow(
                document_id=parse_uuid(s.document_id),
                parent_section_id=parse_uuid(s.parent_section_id) if s.parent_section_id else None,
                heading=s.heading,
                heading_path=s.heading_path,
                level=s.level,
                section_order=s.section_order,
                line_start=s.line_start,
                line_end=s.line_end,
            )
            for s in sections
        ]
        self._session.add_all(rows)
        await self._session.flush()
        return [str(r.id) for r in rows]

    async def update_parents(self, pairs: list[tuple[str, str]]) -> None:
        """Second pass: parent ids are unknown until the rows are flushed."""
        for child_id, parent_id in pairs:
            await self._session.execute(
                sa.update(SectionRow)
                .where(SectionRow.id == parse_uuid(child_id))
                .values(parent_section_id=parse_uuid(parent_id))
            )

    async def delete_by_document(self, document_id: str) -> None:
        await self._session.execute(
            sa.delete(SectionRow).where(SectionRow.document_id == parse_uuid(document_id))
        )


class ChunkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def bulk_create(self, chunks: list[Chunk]) -> list[str]:
        rows = [
            ChunkRow(
                knowledge_base_id=parse_uuid(c.knowledge_base_id),
                document_id=parse_uuid(c.document_id),
                section_id=parse_uuid(c.section_id) if c.section_id else None,
                text=c.text,
                raw_content=c.raw_content,
                heading_path=c.heading_path,
                line_start=c.line_start,
                line_end=c.line_end,
                chunk_type=c.chunk_type,
                parent_chunk_id=parse_uuid(c.parent_chunk_id) if c.parent_chunk_id else None,
                is_parent=c.is_parent,
                chunk_index=c.chunk_index,
                token_count=c.token_count,
                content_hash=c.content_hash,
                product=c.product,
                version=c.version,
                embedding_model=c.embedding_model,
                embedding_model_version=c.embedding_model_version,
            )
            for c in chunks
        ]
        self._session.add_all(rows)
        await self._session.flush()
        return [str(r.id) for r in rows]

    async def get_many(self, chunk_ids: list[str], require_ready: bool = False) -> list[ChunkRow]:
        if not chunk_ids:
            return []
        stmt = sa.select(ChunkRow).where(
            ChunkRow.id.in_([parse_uuid(i) for i in chunk_ids]),
            ChunkRow.deleted_at.is_(None),
        )
        if require_ready:
            # 04 section 34: chunks of a document that never reached READY
            # (e.g. embedding/vector indexing failed) must not be served.
            stmt = stmt.join(DocumentRow, DocumentRow.id == ChunkRow.document_id).where(
                DocumentRow.status == DocumentStatus.READY,
                DocumentRow.deleted_at.is_(None),
            )
        return list((await self._session.execute(stmt)).scalars().all())

    async def soft_delete_by_document(self, document_id: str) -> None:
        await self._session.execute(
            sa.update(ChunkRow)
            .where(ChunkRow.document_id == parse_uuid(document_id))
            .values(deleted_at=datetime.now(UTC))
        )

    async def list_ids_by_document(self, document_id: str) -> list[str]:
        stmt = sa.select(ChunkRow.id).where(
            ChunkRow.document_id == parse_uuid(document_id),
            ChunkRow.deleted_at.is_(None),
        )
        return [str(r) for r in (await self._session.execute(stmt)).scalars().all()]

    async def soft_delete_by_kb(self, kb_id: str) -> None:
        await self._session.execute(
            sa.update(ChunkRow)
            .where(
                ChunkRow.knowledge_base_id == parse_uuid(kb_id),
                ChunkRow.deleted_at.is_(None),
            )
            .values(deleted_at=datetime.now(UTC))
        )

    async def list_deleted_ids(self, limit: int = 200) -> list[str]:
        """Soft-deleted chunks awaiting asynchronous physical cleanup."""
        stmt = (
            sa.select(ChunkRow.id)
            .where(ChunkRow.deleted_at.is_not(None))
            .limit(limit)
        )
        return [str(r) for r in (await self._session.execute(stmt)).scalars().all()]

    async def hard_delete_ids(self, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        await self._session.execute(
            sa.delete(ChunkRow).where(ChunkRow.id.in_([parse_uuid(i) for i in chunk_ids]))
        )

    async def all_ids(self) -> list[str]:
        """Every chunk id, used as the source of truth for orphan reconciliation."""
        stmt = sa.select(ChunkRow.id)
        return [str(r) for r in (await self._session.execute(stmt)).scalars().all()]

    async def delete_by_document(self, document_id: str) -> list[str]:
        """Physical cleanup. Returns deleted chunk ids for Qdrant cleanup."""
        rows = list(
            (
                await self._session.execute(
                    sa.select(ChunkRow.id).where(ChunkRow.document_id == parse_uuid(document_id))
                )
            )
            .scalars()
            .all()
        )
        await self._session.execute(
            sa.delete(ChunkRow).where(ChunkRow.document_id == parse_uuid(document_id))
        )
        return [str(r) for r in rows]


class IngestionJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, job: IngestionJob) -> IngestionJobRow:
        row = IngestionJobRow(
            knowledge_base_id=parse_uuid(job.knowledge_base_id),
            document_id=parse_uuid(job.document_id),
            content_hash=job.content_hash,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get(self, job_id: str) -> IngestionJobRow | None:
        stmt = sa.select(IngestionJobRow).where(IngestionJobRow.id == parse_uuid(job_id))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def update(
        self,
        job_id: str,
        status: JobStatus,
        stage: str | None = None,
        section_count: int | None = None,
        chunk_count: int | None = None,
        embedding_count: int | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        attempt_count: int | None = None,
        next_attempt_at: datetime | None = None,
    ) -> None:
        values: dict = {"status": status}
        if stage is not None:
            values["stage"] = stage
        if section_count is not None:
            values["section_count"] = section_count
        if chunk_count is not None:
            values["chunk_count"] = chunk_count
        if embedding_count is not None:
            values["embedding_count"] = embedding_count
        if error_code is not None:
            values["error_code"] = error_code
            values["error_message"] = error_message
        if attempt_count is not None:
            values["attempt_count"] = attempt_count
        if next_attempt_at is not None:
            values["next_attempt_at"] = next_attempt_at
        if status == JobStatus.RUNNING:
            # Keep the first started_at of the current attempt; later stage
            # transitions must not reset it (stale-job detection relies on it).
            values["started_at"] = sa.func.coalesce(IngestionJobRow.started_at, sa.func.now())
        if status in (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED):
            values["finished_at"] = datetime.now(UTC)
        await self._session.execute(
            sa.update(IngestionJobRow).where(IngestionJobRow.id == parse_uuid(job_id)).values(**values)
        )

    async def requeue(self, job_id: str, next_attempt_at: datetime) -> None:
        """Put a failed/interrupted job back to PENDING for another attempt."""
        await self._session.execute(
            sa.update(IngestionJobRow)
            .where(IngestionJobRow.id == parse_uuid(job_id))
            .values(
                status=JobStatus.PENDING,
                next_attempt_at=next_attempt_at,
                started_at=None,
            )
        )

    async def list_pending(self, limit: int = 10) -> list[IngestionJobRow]:
        now = datetime.now(UTC)
        stmt = (
            sa.select(IngestionJobRow)
            .where(
                IngestionJobRow.status == JobStatus.PENDING,
                sa.or_(
                    IngestionJobRow.next_attempt_at.is_(None),
                    IngestionJobRow.next_attempt_at <= now,
                ),
            )
            .order_by(IngestionJobRow.created_at)
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_stale_running(self, cutoff: datetime, limit: int = 50) -> list[IngestionJobRow]:
        """RUNNING jobs whose attempt started before `cutoff` (worker crashed)."""
        stmt = (
            sa.select(IngestionJobRow)
            .where(
                IngestionJobRow.status == JobStatus.RUNNING,
                IngestionJobRow.started_at.is_not(None),
                IngestionJobRow.started_at < cutoff,
            )
            .order_by(IngestionJobRow.started_at)
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list(
        self,
        document_id: str | None = None,
        status: JobStatus | None = None,
        limit: int = 50,
        cursor: tuple[datetime, str] | None = None,
    ) -> tuple[list[IngestionJobRow], bool]:
        stmt = (
            sa.select(IngestionJobRow)
            .order_by(IngestionJobRow.created_at.desc(), IngestionJobRow.id.desc())
            .limit(limit + 1)
        )
        if document_id is not None:
            stmt = stmt.where(IngestionJobRow.document_id == parse_uuid(document_id))
        if status is not None:
            stmt = stmt.where(IngestionJobRow.status == status)
        stmt = _apply_cursor(stmt, IngestionJobRow, cursor, descending=True)
        rows = list((await self._session.execute(stmt)).scalars().all())
        has_more = len(rows) > limit
        return rows[:limit], has_more


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, kb_id: str) -> ConversationRow:
        row = ConversationRow(knowledge_base_id=parse_uuid(kb_id))
        self._session.add(row)
        await self._session.flush()
        return row

    async def get(self, conversation_id: str) -> ConversationRow | None:
        stmt = sa.select(ConversationRow).where(
            ConversationRow.id == parse_uuid(conversation_id)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        answer_id: str | None = None,
    ) -> None:
        self._session.add(
            ConversationMessageRow(
                conversation_id=parse_uuid(conversation_id),
                role=role,
                content=content,
                answer_id=parse_uuid(answer_id) if answer_id else None,
            )
        )
        await self._session.flush()

    async def recent_messages(self, conversation_id: str, limit: int = 10) -> list[ConversationMessageRow]:
        stmt = (
            sa.select(ConversationMessageRow)
            .where(ConversationMessageRow.conversation_id == parse_uuid(conversation_id))
            .order_by(ConversationMessageRow.created_at.desc())
            .limit(limit)
        )
        rows = list((await self._session.execute(stmt)).scalars().all())
        rows.reverse()
        return rows

    async def list_messages(
        self,
        conversation_id: str,
        limit: int = 50,
        cursor: tuple[datetime, str] | None = None,
    ) -> tuple[list[ConversationMessageRow], bool]:
        """Newest-first page for the public list endpoint."""
        stmt = (
            sa.select(ConversationMessageRow)
            .where(ConversationMessageRow.conversation_id == parse_uuid(conversation_id))
            .order_by(
                ConversationMessageRow.created_at.desc(),
                ConversationMessageRow.id.desc(),
            )
            .limit(limit + 1)
        )
        stmt = _apply_cursor(stmt, ConversationMessageRow, cursor, descending=True)
        rows = list((await self._session.execute(stmt)).scalars().all())
        has_more = len(rows) > limit
        return rows[:limit], has_more


class QueryTraceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, trace: dict) -> str:
        row = QueryTraceRow(**trace)
        self._session.add(row)
        await self._session.flush()
        return str(row.id)

    async def get_by_answer(self, answer_id: str) -> QueryTraceRow | None:
        stmt = sa.select(QueryTraceRow).where(QueryTraceRow.answer_id == parse_uuid(answer_id))
        return (await self._session.execute(stmt)).scalar_one_or_none()


class PromptTemplateRepository:
    """Prompt storage with runtime hot-reload semantics (08-prompt-spec section 2)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_published(self, key: str) -> PromptTemplateRow | None:
        stmt = sa.select(PromptTemplateRow).where(
            PromptTemplateRow.key == key,
            PromptTemplateRow.status == "PUBLISHED",
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_version(self, key: str, version: int) -> PromptTemplateRow | None:
        stmt = sa.select(PromptTemplateRow).where(
            PromptTemplateRow.key == key,
            PromptTemplateRow.version == version,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def next_version(self, key: str) -> int:
        stmt = sa.select(sa.func.max(PromptTemplateRow.version)).where(PromptTemplateRow.key == key)
        current = (await self._session.execute(stmt)).scalar_one_or_none()
        return (current or 0) + 1

    async def create_version(
        self,
        key: str,
        content: str,
        variables: list[str],
        status: str = "DRAFT",
        created_by: str | None = None,
    ) -> PromptTemplateRow:
        row = PromptTemplateRow(
            key=key,
            version=await self.next_version(key),
            content=content,
            variables=variables,
            status=status,
            created_by=created_by,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def publish(self, key: str, version: int) -> None:
        """Publish one version; previously published becomes ARCHIVED.
        PUBLISHED content is never edited in place (08-prompt-spec section 2).
        """
        await self._session.execute(
            sa.update(PromptTemplateRow)
            .where(PromptTemplateRow.key == key, PromptTemplateRow.status == "PUBLISHED")
            .values(status="ARCHIVED", updated_at=datetime.now(UTC))
        )
        await self._session.execute(
            sa.update(PromptTemplateRow)
            .where(PromptTemplateRow.key == key, PromptTemplateRow.version == version)
            .values(status="PUBLISHED", updated_at=datetime.now(UTC))
        )
