"""Repositories. All queries must respect soft delete (deleted_at IS NULL)
and scope filters (knowledge_base_id).
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import parse_uuid
from app.storage.postgres.orm import (
    QueryTraceRow,
)


class QueryTraceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, trace: dict) -> str:
        row = QueryTraceRow(**trace)
        self._session.add(row)
        await self._session.flush()
        return str(row.id)

    async def get_by_answer(self, answer_id: str) -> QueryTraceRow | None:
        stmt = sa.select(QueryTraceRow).where(QueryTraceRow.answer_id == parse_uuid(answer_id))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def delete_older_than(self, cutoff: datetime, limit: int) -> int:
        """删除 ``created_at < cutoff`` 的轨迹，单次最多 ``limit`` 行。

        轨迹每问一行且带多个 JSONB，不设保留策略会无界增长。分批删除是为了
        避免一个长事务锁住整张表；调用方循环直到返回 0。
        """
        ids = (
            sa.select(QueryTraceRow.id)
            .where(QueryTraceRow.created_at < cutoff)
            .order_by(QueryTraceRow.created_at)
            .limit(limit)
            .scalar_subquery()
        )
        result = await self._session.execute(
            sa.delete(QueryTraceRow).where(QueryTraceRow.id.in_(ids))
        )
        return result.rowcount or 0
