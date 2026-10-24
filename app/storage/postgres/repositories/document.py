"""Repositories. All queries must respect soft delete (deleted_at IS NULL)
and scope filters (knowledge_base_id).
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import parse_uuid
from app.domain.document import Document, DocumentStatus
from app.storage.postgres.orm import (
    ChunkRow,
    DocumentRow,
)
from app.storage.postgres.repositories._common import _apply_cursor


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
            source_type=doc.source_type,
            wiki_page_id=parse_uuid(doc.wiki_page_id) if doc.wiki_page_id else None,
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

    async def get_by_wiki_page(self, kb_id: str, wiki_page_id: str) -> DocumentRow | None:
        """Latest live shadow document for a wiki page (11-llm-wiki-spec 3.3)."""
        stmt = (
            sa.select(DocumentRow)
            .where(
                DocumentRow.knowledge_base_id == parse_uuid(kb_id),
                DocumentRow.wiki_page_id == parse_uuid(wiki_page_id),
                DocumentRow.source_type == "wiki",
                DocumentRow.deleted_at.is_(None),
            )
            .order_by(DocumentRow.created_at.desc())
            .limit(1)
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
