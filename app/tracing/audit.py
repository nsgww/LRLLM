"""Audit helper (12-agent-platform-spec §2.5).

Fire-and-forget style: a failure to write the audit row must never break the
business action that triggered it, so errors are logged and swallowed.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.policy.models import Decision, Resource, Subject
from app.storage.postgres.repositories import AuditLogRepository

logger = logging.getLogger(__name__)


def _decision_label(decision: Decision) -> str:
    if decision.requires_approval:
        return "approval_required"
    return "allowed" if decision.allowed else "denied"


async def record_audit(
    session_factory: async_sessionmaker[AsyncSession],
    subject: Subject,
    action: str,
    resource: Resource,
    decision: Decision,
    *,
    approved_by: str | None = None,
    detail: dict | None = None,
) -> bool:
    """写入审计并返回是否成功；调用方（执行闸口）据此对高风险动作 fail-closed。"""
    try:
        async with session_factory() as session:
            await AuditLogRepository(session).create(
                subject_id=subject.id,
                action=action,
                resource_type=resource.type,
                resource_id=resource.id,
                knowledge_base_id=resource.kb_id,
                risk=decision.risk,
                decision=_decision_label(decision),
                requires_approval=decision.requires_approval,
                approved_by=approved_by,
                detail=detail,
            )
            await session.commit()
            return True
    except Exception:
        logger.warning("failed to write audit log for %s", action, exc_info=True)
        return False
