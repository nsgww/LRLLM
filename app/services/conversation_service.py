"""Conversation read service (05-api-spec section 10)."""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError
from app.storage.postgres.orm import ConversationMessageRow, ConversationRow
from app.storage.postgres.repositories import ConversationRepository


class ConversationService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(self, conversation_id: str) -> ConversationRow:
        async with self._session_factory() as session:
            row = await ConversationRepository(session).get(conversation_id)
        if row is None:
            raise AppError(
                code="CONVERSATION_NOT_FOUND",
                message=f"conversation {conversation_id} not found",
                http_status=404,
            )
        return row

    async def list_messages(
        self,
        conversation_id: str,
        limit: int = 50,
        cursor: tuple[datetime, str] | None = None,
    ) -> tuple[list[ConversationMessageRow], bool]:
        await self.get(conversation_id)
        async with self._session_factory() as session:
            return await ConversationRepository(session).list_messages(
                conversation_id, limit, cursor
            )
