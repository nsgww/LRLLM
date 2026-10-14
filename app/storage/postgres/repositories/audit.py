"""Audit log repository (12-agent-platform-spec §2.5)."""

from __future__ import annotations

import uuid

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
