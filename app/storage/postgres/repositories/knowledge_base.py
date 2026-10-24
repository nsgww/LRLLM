"""Repositories. All queries must respect soft delete (deleted_at IS NULL)
and scope filters (knowledge_base_id).
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import parse_uuid
from app.storage.postgres.orm import (
    KnowledgeBaseRow,
)
from app.storage.postgres.repositories._common import _apply_cursor


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
