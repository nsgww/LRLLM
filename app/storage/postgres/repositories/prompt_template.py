"""Repositories. All queries must respect soft delete (deleted_at IS NULL)
and scope filters (knowledge_base_id).
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.postgres.orm import (
    PromptTemplateRow,
)


class PromptTemplateRepository:
    """Prompt storage with runtime hot-reload semantics (08-prompt-spec section 2)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_published(self, key: str) -> PromptTemplateRow | None:
        stmt = sa.select(PromptTemplateRow).where(
            PromptTemplateRow.key == key,
            PromptTemplateRow.status == "PUBLISHED",
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_version(self, key: str, version: int) -> PromptTemplateRow | None:
        stmt = sa.select(PromptTemplateRow).where(
            PromptTemplateRow.key == key,
            PromptTemplateRow.version == version,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def next_version(self, key: str) -> int:
        stmt = sa.select(sa.func.max(PromptTemplateRow.version)).where(PromptTemplateRow.key == key)
        current = (await self._session.execute(stmt)).scalar_one_or_none()
        return (current or 0) + 1

    async def create_version(
        self,
        key: str,
        content: str,
        variables: list[str],
        status: str = "DRAFT",
        created_by: str | None = None,
    ) -> PromptTemplateRow:
        row = PromptTemplateRow(
            key=key,
            version=await self.next_version(key),
            content=content,
            variables=variables,
            status=status,
            created_by=created_by,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def publish(self, key: str, version: int) -> None:
        """Publish one version; previously published becomes ARCHIVED.
        PUBLISHED content is never edited in place (08-prompt-spec section 2).
        """
        await self._session.execute(
            sa.update(PromptTemplateRow)
            .where(PromptTemplateRow.key == key, PromptTemplateRow.status == "PUBLISHED")
            .values(status="ARCHIVED", updated_at=datetime.now(UTC))
        )
        await self._session.execute(
            sa.update(PromptTemplateRow)
            .where(PromptTemplateRow.key == key, PromptTemplateRow.version == version)
            .values(status="PUBLISHED", updated_at=datetime.now(UTC))
        )
