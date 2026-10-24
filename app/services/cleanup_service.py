"""后台物理清理（04 第 25 节，09 第 11 节）。

软删除使行立即对检索不可见；本服务由入库 Worker 周期执行，
完成最终的物理清理：

- 清理软删除的 Chunk：先删除 Qdrant 中的点，再删除 PG 行；
- 清理软删除的 Document：当其所有 Chunk 都已物理消失后再物理删除
  （外键级联会一并清理 Section 与 Ingestion Job）；
- 对账孤儿 Qdrant 点（Point ID 在 chunks.id 中不存在）；
- 按保留期清理 query_traces / audit_logs（两者每请求/每动作一行，
  不设上限会无界增长）。
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.storage.base import VectorStore
from app.storage.postgres.repositories import (
    AuditLogRepository,
    ChunkRepository,
    DocumentRepository,
    QueryTraceRepository,
    WikiPageRepository,
)

logger = logging.getLogger(__name__)

# 单轮保留清理最多删除的批次数：防止首次接入时把整张表一次删空、
# 长时间占住表锁。剩余部分下一轮继续。
_MAX_RETENTION_BATCHES = 50


@dataclass
class CleanupReport:
    chunks_purged: int = 0
    documents_purged: int = 0
    wiki_pages_purged: int = 0
    orphans_removed: int = 0
    traces_purged: int = 0
    audit_logs_purged: int = 0


class CleanupService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        vector_store: VectorStore,
        batch_size: int = 200,
        trace_retention_days: int = 0,
        audit_retention_days: int = 0,
    ) -> None:
        self._session_factory = session_factory
        self._vector_store = vector_store
        self._batch_size = batch_size
        # 0 表示永久保留（默认关闭，避免升级后意外删数据）
        self._trace_retention_days = trace_retention_days
        self._audit_retention_days = audit_retention_days

    async def run_once(self) -> CleanupReport:
        report = CleanupReport()
        report.chunks_purged = await self._purge_chunks()
        report.documents_purged = await self._purge_documents()
        report.wiki_pages_purged = await self._purge_wiki_pages()
        report.traces_purged = await self._purge_traces()
        report.audit_logs_purged = await self._purge_audit_logs()
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

    async def _purge_wiki_pages(self) -> int:
        """Physically purge soft-deleted wiki pages (11 §8.3).

        Revisions cascade via the page_id FK ON DELETE CASCADE; the wiki
        shadow document/chunk are purged by the document/chunk passes above.
        """
        async with self._session_factory() as session:
            repo = WikiPageRepository(session)
            page_ids = await repo.list_deleted_ids(self._batch_size)
            if not page_ids:
                return 0
            await repo.hard_delete_ids(page_ids)
            await session.commit()
            return len(page_ids)

    async def _purge_traces(self) -> int:
        """按保留期批量删除查询轨迹；0 天表示永久保留。"""
        if self._trace_retention_days <= 0:
            return 0
        cutoff = datetime.now(UTC) - timedelta(days=self._trace_retention_days)
        return await self._delete_batches(cutoff, kind="traces")

    async def _purge_audit_logs(self) -> int:
        """按保留期批量删除审计日志；0 天表示永久保留（合规场景常用）。"""
        if self._audit_retention_days <= 0:
            return 0
        cutoff = datetime.now(UTC) - timedelta(days=self._audit_retention_days)
        return await self._delete_batches(cutoff, kind="audit")

    async def _delete_batches(self, cutoff: datetime, *, kind: str) -> int:
        """逐批删除，单轮最多 ``_MAX_RETENTION_BATCHES`` 批，避免长时间锁表。"""
        deleted = 0
        for _ in range(_MAX_RETENTION_BATCHES):
            async with self._session_factory() as session:
                if kind == "traces":
                    batch = await QueryTraceRepository(session).delete_older_than(
                        cutoff, self._batch_size
                    )
                else:
                    batch = await AuditLogRepository(session).delete_older_than(
                        cutoff, self._batch_size
                    )
                await session.commit()
            deleted += batch
            if batch < self._batch_size:
                break
        if deleted:
            logger.info("retention purge removed %s %s row(s) older than %s", deleted, kind, cutoff)
        return deleted

    async def reconcile_orphans(self) -> int:
        """Delete Qdrant points whose chunk row no longer exists (09 section 11).

        Chunk ids are streamed in batches so reconciliation does not load the
        whole chunks table into memory. The point-id set is built once (not
        per batch) — rebuilding it inside the loop is O(batches × points).
        """
        point_ids = set(await self._vector_store.list_point_ids())
        if not point_ids:
            return 0
        known: set[str] = set()
        async with self._session_factory() as session:
            repo = ChunkRepository(session)
            async for batch in repo.iter_id_batches():
                known.update(batch)
                # Point ids are the same set; stop early once every point is
                # accounted for.
                if point_ids <= known:
                    break
        orphans = [point_id for point_id in point_ids if point_id not in known]
        if orphans:
            await self._vector_store.delete(orphans)
            logger.warning("removed %s orphan vector point(s)", len(orphans))
        return len(orphans)
