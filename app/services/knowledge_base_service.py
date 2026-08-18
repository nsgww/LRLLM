"""Knowledge base management (05-api-spec section 5)."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError
from app.storage.postgres.orm import KnowledgeBaseRow
from app.storage.postgres.repositories import KnowledgeBaseRepository


class KnowledgeBaseService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(self, name: str, description: str | None) -> KnowledgeBaseRow:
        async with self._session_factory() as session:
            row = await KnowledgeBaseRepository(session).create(name, description)
            await session.commit()
            return row

    async def get(self, kb_id: str) -> KnowledgeBaseRow:
        async with self._session_factory() as session:
            row = await KnowledgeBaseRepository(session).get(kb_id)
        if row is None:
            raise AppError(
                code="KNOWLEDGE_BASE_NOT_FOUND",
                message=f"knowledge base {kb_id} not found",
                http_status=404,
            )
        return row

    async def list(self, limit: int = 50) -> list[KnowledgeBaseRow]:
        async with self._session_factory() as session:
            return await KnowledgeBaseRepository(session).list(limit)

    async def soft_delete(self, kb_id: str) -> None:
        await self.get(kb_id)
        async with self._session_factory() as session:
            await KnowledgeBaseRepository(session).soft_delete(kb_id)
            await session.commit()
