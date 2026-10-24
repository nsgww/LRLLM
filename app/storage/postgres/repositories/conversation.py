"""Repositories. All queries must respect soft delete (deleted_at IS NULL)
and scope filters (knowledge_base_id).
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import parse_uuid
from app.storage.postgres.orm import (
    ConversationMessageRow,
    ConversationRow,
)
from app.storage.postgres.repositories._common import _apply_cursor


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, kb_id: str) -> ConversationRow:
        row = ConversationRow(knowledge_base_id=parse_uuid(kb_id))
        self._session.add(row)
        await self._session.flush()
        return row

    async def list_by_kb(self, kb_id: str, limit: int = 50) -> list[ConversationRow]:
        """按知识库列出会话，最新在前（05 节 10）。"""
        stmt = (
            sa.select(ConversationRow)
            .where(ConversationRow.knowledge_base_id == parse_uuid(kb_id))
            .order_by(ConversationRow.created_at.desc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

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
