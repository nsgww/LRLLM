"""Repositories. All queries must respect soft delete (deleted_at IS NULL)
and scope filters (knowledge_base_id).
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import parse_uuid
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
from app.storage.postgres.repositories._common import _apply_cursor

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
        """Second pass: parent ids are unknown until the rows are flushed.

        Batched into a single CASE expression instead of one UPDATE per row.
        """
        if not pairs:
            return
        child_col = SectionRow.id
        whens = [(child_col == parse_uuid(child), parse_uuid(parent)) for child, parent in pairs]
        await self._session.execute(
            sa.update(SectionRow)
            .where(child_col.in_([parse_uuid(child) for child, _ in pairs]))
            .values(parent_section_id=sa.case(*whens, else_=SectionRow.parent_section_id))
        )

    async def delete_by_document(self, document_id: str) -> None:
        await self._session.execute(
            sa.delete(SectionRow).where(SectionRow.document_id == parse_uuid(document_id))
        )

    async def count_by_document(self, document_id: str) -> int:
        stmt = sa.select(sa.func.count(SectionRow.id)).where(
            SectionRow.document_id == parse_uuid(document_id)
        )
        return int((await self._session.execute(stmt)).scalar_one() or 0)
