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
