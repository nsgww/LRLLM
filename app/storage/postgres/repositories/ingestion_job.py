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

class IngestionJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, job: IngestionJob) -> IngestionJobRow:
        row = IngestionJobRow(
            knowledge_base_id=parse_uuid(job.knowledge_base_id),
            document_id=parse_uuid(job.document_id),
            content_hash=job.content_hash,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get(self, job_id: str) -> IngestionJobRow | None:
        stmt = sa.select(IngestionJobRow).where(IngestionJobRow.id == parse_uuid(job_id))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def find_active(self, document_id: str) -> IngestionJobRow | None:
        """Latest still-active (PENDING/RUNNING) job for a document, if any.

        Used by reindex to avoid enqueuing a duplicate job while one is already
        in flight (which would flood the worker and re-burn embedding quota).
        """
        stmt = (
            sa.select(IngestionJobRow)
            .where(
                IngestionJobRow.document_id == parse_uuid(document_id),
                IngestionJobRow.status.in_([JobStatus.PENDING, JobStatus.RUNNING]),
            )
            .order_by(IngestionJobRow.created_at.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def update(
        self,
        job_id: str,
        status: JobStatus,
        stage: str | None = None,
        section_count: int | None = None,
        chunk_count: int | None = None,
        embedding_count: int | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        attempt_count: int | None = None,
        next_attempt_at: datetime | None = None,
    ) -> None:
        values: dict = {"status": status}
        if stage is not None:
            values["stage"] = stage
        if section_count is not None:
            values["section_count"] = section_count
        if chunk_count is not None:
            values["chunk_count"] = chunk_count
        if embedding_count is not None:
            values["embedding_count"] = embedding_count
        if error_code is not None:
            values["error_code"] = error_code
            values["error_message"] = error_message
        if attempt_count is not None:
            values["attempt_count"] = attempt_count
        if next_attempt_at is not None:
            values["next_attempt_at"] = next_attempt_at
        if status == JobStatus.RUNNING:
            # Keep the first started_at of the current attempt; later stage
            # transitions must not reset it (stale-job detection relies on it).
            values["started_at"] = sa.func.coalesce(IngestionJobRow.started_at, sa.func.now())
        if status in (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED):
            values["finished_at"] = datetime.now(UTC)
        await self._session.execute(
            sa.update(IngestionJobRow).where(IngestionJobRow.id == parse_uuid(job_id)).values(**values)
        )

    async def requeue(self, job_id: str, next_attempt_at: datetime) -> None:
        """Put a failed/interrupted job back to PENDING for another attempt."""
        await self._session.execute(
            sa.update(IngestionJobRow)
            .where(IngestionJobRow.id == parse_uuid(job_id))
            .values(
                status=JobStatus.PENDING,
                next_attempt_at=next_attempt_at,
                started_at=None,
            )
        )

    async def list_pending(self, limit: int = 10) -> list[IngestionJobRow]:
        now = datetime.now(UTC)
        stmt = (
            sa.select(IngestionJobRow)
            .where(
                IngestionJobRow.status == JobStatus.PENDING,
                sa.or_(
                    IngestionJobRow.next_attempt_at.is_(None),
                    IngestionJobRow.next_attempt_at <= now,
                ),
            )
            .order_by(IngestionJobRow.created_at)
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def claim_pending(self, limit: int = 10) -> list[str]:
        """Atomically claim due PENDING jobs and mark them RUNNING.

        The ``SELECT ... FOR UPDATE SKIP LOCKED`` and the flip to RUNNING happen
        in a single statement (committed by the caller). Flipping the status in
        the same statement — rather than a bare SELECT — closes the window where
        a second worker replica could re-claim the still-PENDING row before the
        pipeline sets it RUNNING in a later transaction (which would process the
        same job twice).

        ``attempt_count`` is intentionally NOT touched here: the pipeline owns
        attempt accounting at its PARSE transition. ``started_at`` is stamped now
        so stale-job recovery measures from claim time.
        """
        now = datetime.now(UTC)
        due = (
            sa.select(IngestionJobRow.id)
            .where(
                IngestionJobRow.status == JobStatus.PENDING,
                sa.or_(
                    IngestionJobRow.next_attempt_at.is_(None),
                    IngestionJobRow.next_attempt_at <= now,
                ),
            )
            .order_by(IngestionJobRow.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .scalar_subquery()
        )
        stmt = (
            sa.update(IngestionJobRow)
            .where(IngestionJobRow.id.in_(due))
            .values(status=JobStatus.RUNNING, started_at=sa.func.now())
            .returning(IngestionJobRow.id)
        )
        return [str(r) for r in (await self._session.execute(stmt)).scalars().all()]

    async def list_stale_running(self, cutoff: datetime, limit: int = 50) -> list[IngestionJobRow]:
        """RUNNING jobs whose attempt started before `cutoff` (worker crashed)."""
        stmt = (
            sa.select(IngestionJobRow)
            .where(
                IngestionJobRow.status == JobStatus.RUNNING,
                IngestionJobRow.started_at.is_not(None),
                IngestionJobRow.started_at < cutoff,
            )
            .order_by(IngestionJobRow.started_at)
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list(
        self,
        document_id: str | None = None,
        status: JobStatus | None = None,
        limit: int = 50,
        cursor: tuple[datetime, str] | None = None,
        kb_id: str | None = None,
    ) -> tuple[list[IngestionJobRow], bool]:
        stmt = (
            sa.select(IngestionJobRow)
            .order_by(IngestionJobRow.created_at.desc(), IngestionJobRow.id.desc())
            .limit(limit + 1)
        )
        if kb_id is not None:
            stmt = stmt.where(IngestionJobRow.knowledge_base_id == parse_uuid(kb_id))
        if document_id is not None:
            stmt = stmt.where(IngestionJobRow.document_id == parse_uuid(document_id))
        if status is not None:
            stmt = stmt.where(IngestionJobRow.status == status)
        stmt = _apply_cursor(stmt, IngestionJobRow, cursor, descending=True)
        rows = list((await self._session.execute(stmt)).scalars().all())
        has_more = len(rows) > limit
        return rows[:limit], has_more
