"""Repositories. All queries must respect soft delete (deleted_at IS NULL)
and scope filters (knowledge_base_id).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

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
            KnowledgeBaseRow.id == uuid.UUID(kb_id),
            KnowledgeBaseRow.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list(self, limit: int = 50) -> list[KnowledgeBaseRow]:
        stmt = (
            sa.select(KnowledgeBaseRow)
            .where(KnowledgeBaseRow.deleted_at.is_(None))
            .order_by(KnowledgeBaseRow.created_at.desc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def soft_delete(self, kb_id: str) -> None:
        await self._session.execute(
            sa.update(KnowledgeBaseRow)
            .where(KnowledgeBaseRow.id == uuid.UUID(kb_id))
            .values(deleted_at=datetime.now(UTC))
        )


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, doc: Document) -> DocumentRow:
        row = DocumentRow(
            knowledge_base_id=uuid.UUID(doc.knowledge_base_id),
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
            DocumentRow.id == uuid.UUID(document_id),
            DocumentRow.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_hash(self, kb_id: str, content_hash: str) -> DocumentRow | None:
        stmt = sa.select(DocumentRow).where(
            DocumentRow.knowledge_base_id == uuid.UUID(kb_id),
            DocumentRow.content_hash == content_hash,
            DocumentRow.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list(self, kb_id: str, limit: int = 50) -> list[DocumentRow]:
        stmt = (
            sa.select(DocumentRow)
            .where(
                DocumentRow.knowledge_base_id == uuid.UUID(kb_id),
                DocumentRow.deleted_at.is_(None),
            )
            .order_by(DocumentRow.created_at.desc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def update_status(
        self,
        document_id: str,
        status: DocumentStatus,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        await self._session.execute(
            sa.update(DocumentRow)
            .where(DocumentRow.id == uuid.UUID(document_id))
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
            .where(DocumentRow.id == uuid.UUID(document_id))
            .values(deleted_at=datetime.now(UTC))
        )

    async def distinct_product_versions(self, kb_id: str) -> list[dict]:
        """Known products/versions for query_understanding grounding (08 section 4.1)."""
        stmt = (
            sa.select(DocumentRow.product, DocumentRow.version)
            .where(
                DocumentRow.knowledge_base_id == uuid.UUID(kb_id),
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
            .where(DocumentRow.id == uuid.UUID(document_id))
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
            .where(DocumentRow.id == uuid.UUID(document_id))
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
                document_id=uuid.UUID(s.document_id),
                parent_section_id=uuid.UUID(s.parent_section_id) if s.parent_section_id else None,
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

    async def delete_by_document(self, document_id: str) -> None:
        await self._session.execute(
            sa.delete(SectionRow).where(SectionRow.document_id == uuid.UUID(document_id))
        )


class ChunkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def bulk_create(self, chunks: list[Chunk]) -> list[str]:
        rows = [
            ChunkRow(
                knowledge_base_id=uuid.UUID(c.knowledge_base_id),
                document_id=uuid.UUID(c.document_id),
                section_id=uuid.UUID(c.section_id) if c.section_id else None,
                text=c.text,
                raw_content=c.raw_content,
                heading_path=c.heading_path,
                line_start=c.line_start,
                line_end=c.line_end,
                chunk_type=c.chunk_type,
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

    async def get_many(self, chunk_ids: list[str]) -> list[ChunkRow]:
        if not chunk_ids:
            return []
        stmt = sa.select(ChunkRow).where(
            ChunkRow.id.in_([uuid.UUID(i) for i in chunk_ids]),
            ChunkRow.deleted_at.is_(None),
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def soft_delete_by_document(self, document_id: str) -> None:
        await self._session.execute(
            sa.update(ChunkRow)
            .where(ChunkRow.document_id == uuid.UUID(document_id))
            .values(deleted_at=datetime.now(UTC))
        )

    async def list_ids_by_document(self, document_id: str) -> list[str]:
        stmt = sa.select(ChunkRow.id).where(
            ChunkRow.document_id == uuid.UUID(document_id),
            ChunkRow.deleted_at.is_(None),
        )
        return [str(r) for r in (await self._session.execute(stmt)).scalars().all()]

    async def delete_by_document(self, document_id: str) -> list[str]:
        """Physical cleanup. Returns deleted chunk ids for Qdrant cleanup."""
        rows = list(
            (
                await self._session.execute(
                    sa.select(ChunkRow.id).where(ChunkRow.document_id == uuid.UUID(document_id))
                )
            )
            .scalars()
            .all()
        )
        await self._session.execute(
            sa.delete(ChunkRow).where(ChunkRow.document_id == uuid.UUID(document_id))
        )
        return [str(r) for r in rows]


class IngestionJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, job: IngestionJob) -> IngestionJobRow:
        row = IngestionJobRow(
            knowledge_base_id=uuid.UUID(job.knowledge_base_id),
            document_id=uuid.UUID(job.document_id),
            content_hash=job.content_hash,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get(self, job_id: str) -> IngestionJobRow | None:
        stmt = sa.select(IngestionJobRow).where(IngestionJobRow.id == uuid.UUID(job_id))
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
        if status == JobStatus.RUNNING:
            values["started_at"] = datetime.now(UTC)
        if status in (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED):
            values["finished_at"] = datetime.now(UTC)
        await self._session.execute(
            sa.update(IngestionJobRow).where(IngestionJobRow.id == uuid.UUID(job_id)).values(**values)
        )

    async def list_pending(self, limit: int = 10) -> list[IngestionJobRow]:
        stmt = (
            sa.select(IngestionJobRow)
            .where(IngestionJobRow.status == JobStatus.PENDING)
            .order_by(IngestionJobRow.created_at)
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list(
        self,
        document_id: str | None = None,
        limit: int = 50,
    ) -> list[IngestionJobRow]:
        stmt = sa.select(IngestionJobRow).order_by(IngestionJobRow.created_at.desc()).limit(limit)
        if document_id is not None:
            stmt = stmt.where(IngestionJobRow.document_id == uuid.UUID(document_id))
        return list((await self._session.execute(stmt)).scalars().all())


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, kb_id: str) -> ConversationRow:
        row = ConversationRow(knowledge_base_id=uuid.UUID(kb_id))
        self._session.add(row)
        await self._session.flush()
        return row

    async def get(self, conversation_id: str) -> ConversationRow | None:
        stmt = sa.select(ConversationRow).where(
            ConversationRow.id == uuid.UUID(conversation_id)
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
                conversation_id=uuid.UUID(conversation_id),
                role=role,
                content=content,
                answer_id=uuid.UUID(answer_id) if answer_id else None,
            )
        )
        await self._session.flush()

    async def recent_messages(self, conversation_id: str, limit: int = 10) -> list[ConversationMessageRow]:
        stmt = (
            sa.select(ConversationMessageRow)
            .where(ConversationMessageRow.conversation_id == uuid.UUID(conversation_id))
            .order_by(ConversationMessageRow.created_at.desc())
            .limit(limit)
        )
        rows = list((await self._session.execute(stmt)).scalars().all())
        rows.reverse()
        return rows


class QueryTraceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, trace: dict) -> str:
        row = QueryTraceRow(**trace)
        self._session.add(row)
        await self._session.flush()
        return str(row.id)

    async def get_by_answer(self, answer_id: str) -> QueryTraceRow | None:
        stmt = sa.select(QueryTraceRow).where(QueryTraceRow.answer_id == uuid.UUID(answer_id))
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
