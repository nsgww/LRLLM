"""Repositories. All queries must respect soft delete (deleted_at IS NULL)
and scope filters (knowledge_base_id).
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import parse_uuid
from app.domain.chunk import Chunk
from app.domain.document import DocumentStatus
from app.storage.postgres.orm import (
    ChunkRow,
    DocumentRow,
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

    async def count_by_document(self, document_id: str, *, only_children: bool = False) -> int:
        """Chunk count for a document. ``only_children`` counts embedded child
        chunks (parent chunks are context-only and carry no vector)."""
        stmt = sa.select(sa.func.count(ChunkRow.id)).where(
            ChunkRow.document_id == parse_uuid(document_id),
            ChunkRow.deleted_at.is_(None),
        )
        if only_children:
            stmt = stmt.where(ChunkRow.is_parent.is_(False))
        return int((await self._session.execute(stmt)).scalar_one() or 0)

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

    async def iter_id_batches(self, batch_size: int = 5000):
        """Yield chunk id batches via keyset pagination.

        Orphan reconciliation only needs set membership; streaming by id avoids
        loading the whole table into memory at once.
        """
        last_id = None
        while True:
            stmt = sa.select(ChunkRow.id).order_by(ChunkRow.id).limit(batch_size)
            if last_id is not None:
                stmt = stmt.where(ChunkRow.id > last_id)
            rows = [r for r in (await self._session.execute(stmt)).scalars().all()]
            if not rows:
                return
            yield [str(r) for r in rows]
            last_id = rows[-1]

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
