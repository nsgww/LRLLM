"""Repositories. All queries must respect soft delete (deleted_at IS NULL)
and scope filters (knowledge_base_id).
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import parse_uuid
from app.domain.wiki import WikiPage, WikiRevision, WikiStatus
from app.storage.postgres.orm import WikiPageRow, WikiRevisionRow
from app.storage.postgres.repositories._common import _apply_cursor


class WikiPageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, page: WikiPage) -> WikiPageRow:
        row = WikiPageRow(
            knowledge_base_id=parse_uuid(page.knowledge_base_id),
            slug=page.slug,
            title=page.title,
            summary=page.summary,
            status=page.status,
            revision_count=page.revision_count,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get(self, page_id: str) -> WikiPageRow | None:
        stmt = sa.select(WikiPageRow).where(
            WikiPageRow.id == parse_uuid(page_id),
            WikiPageRow.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_published_by_slug(self, kb_id: str, slug: str) -> WikiPageRow | None:
        """Live PUBLISHED page for a (kb, slug) — the merge target on distill."""
        stmt = sa.select(WikiPageRow).where(
            WikiPageRow.knowledge_base_id == parse_uuid(kb_id),
            WikiPageRow.slug == slug,
            WikiPageRow.status == WikiStatus.PUBLISHED,
            WikiPageRow.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list(
        self,
        kb_id: str,
        limit: int = 50,
        cursor: tuple[datetime, str] | None = None,
    ) -> tuple[list[WikiPageRow], bool]:
        stmt = (
            sa.select(WikiPageRow)
            .where(
                WikiPageRow.knowledge_base_id == parse_uuid(kb_id),
                WikiPageRow.deleted_at.is_(None),
            )
            # 排序列必须与 keyset 游标列一致（pagination 用 created_at 编码），
            # 否则 touch() 抬升 updated_at 后翻页会漏页/重页。
            .order_by(WikiPageRow.created_at.desc(), WikiPageRow.id.desc())
            .limit(limit + 1)
        )
        stmt = _apply_cursor(stmt, WikiPageRow, cursor, descending=True)
        rows = list((await self._session.execute(stmt)).scalars().all())
        has_more = len(rows) > limit
        return rows[:limit], has_more

    async def touch(
        self,
        page_id: str,
        *,
        title: str,
        summary: str,
        revision_count: int,
    ) -> None:
        await self._session.execute(
            sa.update(WikiPageRow)
            .where(WikiPageRow.id == parse_uuid(page_id))
            .values(
                title=title,
                summary=summary,
                revision_count=revision_count,
                updated_at=datetime.now(UTC),
            )
        )

    async def soft_delete(self, page_id: str) -> None:
        await self._session.execute(
            sa.update(WikiPageRow)
            .where(WikiPageRow.id == parse_uuid(page_id))
            .values(deleted_at=datetime.now(UTC))
        )

    async def soft_delete_by_kb(self, kb_id: str) -> None:
        """Cascade soft delete when a knowledge base is removed."""
        await self._session.execute(
            sa.update(WikiPageRow)
            .where(
                WikiPageRow.knowledge_base_id == parse_uuid(kb_id),
                WikiPageRow.deleted_at.is_(None),
            )
            .values(deleted_at=datetime.now(UTC))
        )

    async def list_deleted_ids(self, limit: int) -> list:
        """Ids of soft-deleted pages pending physical purge."""
        stmt = (
            sa.select(WikiPageRow.id)
            .where(WikiPageRow.deleted_at.is_not(None))
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def hard_delete_ids(self, ids: list) -> None:
        """Physically delete pages; revisions cascade via page_id FK."""
        if not ids:
            return
        await self._session.execute(sa.delete(WikiPageRow).where(WikiPageRow.id.in_(ids)))


class WikiRevisionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, rev: WikiRevision) -> WikiRevisionRow:
        row = WikiRevisionRow(
            page_id=parse_uuid(rev.page_id),
            version=rev.version,
            content=rev.content,
            source_answer_id=(
                parse_uuid(rev.source.answer_id) if rev.source.answer_id else None
            ),
            source_query=rev.source.query,
            evidence=rev.source.evidence,
            change_note=rev.change_note,
            status=rev.status,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def next_version(self, page_id: str) -> int:
        stmt = sa.select(sa.func.max(WikiRevisionRow.version)).where(
            WikiRevisionRow.page_id == parse_uuid(page_id)
        )
        current = (await self._session.execute(stmt)).scalar()
        return (current or 0) + 1

    async def get_latest(self, page_id: str) -> WikiRevisionRow | None:
        stmt = (
            sa.select(WikiRevisionRow)
            .where(WikiRevisionRow.page_id == parse_uuid(page_id))
            .order_by(WikiRevisionRow.version.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_by_page(
        self,
        page_id: str,
        limit: int = 50,
        cursor: tuple[datetime, str] | None = None,
    ) -> tuple[list[WikiRevisionRow], bool]:
        stmt = (
            sa.select(WikiRevisionRow)
            .where(WikiRevisionRow.page_id == parse_uuid(page_id))
            .order_by(WikiRevisionRow.created_at.desc(), WikiRevisionRow.id.desc())
            .limit(limit + 1)
        )
        stmt = _apply_cursor(stmt, WikiRevisionRow, cursor, descending=True)
        rows = list((await self._session.execute(stmt)).scalars().all())
        has_more = len(rows) > limit
        return rows[:limit], has_more
