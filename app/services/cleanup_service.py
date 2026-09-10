"""后台物理清理（04 第 25 节，09 第 11 节）。

软删除使行立即对检索不可见；本服务由入库 Worker 周期执行，
完成最终的物理清理：

- 清理软删除的 Chunk：先删除 Qdrant 中的点，再删除 PG 行；
- 清理软删除的 Document：当其所有 Chunk 都已物理消失后再物理删除
  （外键级联会一并清理 Section 与 Ingestion Job）；
- 对账孤儿 Qdrant 点（Point ID 在 chunks.id 中不存在）。
"""

import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.storage.base import VectorStore
from app.storage.postgres.repositories import ChunkRepository, DocumentRepository

logger = logging.getLogger(__name__)


@dataclass
class CleanupReport:
    chunks_purged: int = 0
    documents_purged: int = 0
    orphans_removed: int = 0


class CleanupService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        vector_store: VectorStore,
        batch_size: int = 200,
    ) -> None:
        self._session_factory = session_factory
        self._vector_store = vector_store
        self._batch_size = batch_size

    async def run_once(self) -> CleanupReport:
        report = CleanupReport()
        report.chunks_purged = await self._purge_chunks()
        report.documents_purged = await self._purge_documents()
        return report

    async def _purge_chunks(self) -> int:
        async with self._session_factory() as session:
            repo = ChunkRepository(session)
            chunk_ids = await repo.list_deleted_ids(self._batch_size)
            if not chunk_ids:
                return 0
            # Remove vectors first so a crash never leaves a point without a row.
            await self._vector_store.delete(chunk_ids)
            await repo.hard_delete_ids(chunk_ids)
            await session.commit()
            return len(chunk_ids)

    async def _purge_documents(self) -> int:
        async with self._session_factory() as session:
            repo = DocumentRepository(session)
            document_ids = await repo.list_purgeable_ids(self._batch_size)
            if not document_ids:
                return 0
            await repo.hard_delete_ids(document_ids)
            await session.commit()
            return len(document_ids)

    async def reconcile_orphans(self) -> int:
        """Delete Qdrant points whose chunk row no longer exists (09 section 11)."""
        async with self._session_factory() as session:
            known = set(await ChunkRepository(session).all_ids())
        point_ids = await self._vector_store.list_point_ids()
        orphans = [point_id for point_id in point_ids if point_id not in known]
        if orphans:
            await self._vector_store.delete(orphans)
            logger.warning("removed %s orphan vector point(s)", len(orphans))
        return len(orphans)
