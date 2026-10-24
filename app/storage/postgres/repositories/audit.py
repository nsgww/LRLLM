"""Audit log repository (12-agent-platform-spec §2.5)."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.postgres.orm import AuditLogRow


class AuditLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        subject_id: str,
        action: str,
        resource_type: str,
        resource_id: str | None = None,
        knowledge_base_id: str | None = None,
        risk: str = "low",
        decision: str = "allowed",
        requires_approval: bool = False,
        approved_by: str | None = None,
        detail: dict | None = None,
    ) -> AuditLogRow:
        kb_uuid: uuid.UUID | None = None
        if knowledge_base_id:
            try:
                kb_uuid = uuid.UUID(str(knowledge_base_id))
            except (ValueError, AttributeError):
                kb_uuid = None
        row = AuditLogRow(
            subject_id=subject_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            knowledge_base_id=kb_uuid,
            risk=risk,
            decision=decision,
            requires_approval=requires_approval,
            approved_by=approved_by,
            detail=detail or {},
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def delete_older_than(self, cutoff: datetime, limit: int) -> int:
        """删除 ``created_at < cutoff`` 的审计行，单次最多 ``limit`` 行。

        审计保留期通常远长于轨迹（合规留痕），由调用方按配置决定 cutoff。
        """
        ids = (
            sa.select(AuditLogRow.id)
            .where(AuditLogRow.created_at < cutoff)
            .order_by(AuditLogRow.created_at)
            .limit(limit)
            .scalar_subquery()
        )
        result = await self._session.execute(
            sa.delete(AuditLogRow).where(AuditLogRow.id.in_(ids))
        )
        return result.rowcount or 0
