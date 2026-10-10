"""Knowledge base management (05-api-spec section 5)."""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError
from app.storage.base import VectorStore
from app.storage.postgres.orm import KnowledgeBaseRow
from app.storage.postgres.repositories import (
    ChunkRepository,
    DocumentRepository,
    KnowledgeBaseRepository,
)


class KnowledgeBaseService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        vector_store: VectorStore | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._vector_store = vector_store

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

    async def list(
        self, limit: int = 50, cursor: tuple[datetime, str] | None = None
    ) -> tuple[list[KnowledgeBaseRow], bool]:
        async with self._session_factory() as session:
            return await KnowledgeBaseRepository(session).list(limit, cursor)

    async def soft_delete(self, kb_id: str) -> None:
        """Soft delete the KB and cascade to Document/Chunk, then drop vectors.

        Vectors must be removed here: PostgreSQL rows get physically purged by
        CleanupService, after which the Qdrant points become orphans that only
        a *worker restart* would reconcile (05 section 5, 09 section 11).
        A long-running worker would otherwise hold the vectors forever, which
        is both a storage-cost and a "delete was not honoured" problem.
        """
        await self.get(kb_id)
        async with self._session_factory() as session:
            await ChunkRepository(session).soft_delete_by_kb(kb_id)
            await DocumentRepository(session).soft_delete_by_kb(kb_id)
            await KnowledgeBaseRepository(session).soft_delete(kb_id)
            await session.commit()
        if self._vector_store is not None:
            # Served by a payload filter, so no id list is materialised.
            await self._vector_store.delete_by_knowledge_base(kb_id)
