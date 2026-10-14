"""Policy + Audit 门控（12-agent-platform-spec §2.3/§2.4）。

Business Tool 连内部系统、是风险敞口，执行前必须经过此处：
``PolicyEngine.evaluate`` 判定 → ``record_audit`` 落审计 → 拒绝/需审批则
不执行业务函数。把真实内部 API / DB 调用放进 ``fn`` 即可，门控骨架不变。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.observability.metrics import get_metrics
from app.policy import PolicyEngine
from app.policy.models import Resource, Subject
from app.tracing.audit import record_audit


def make_guarded_handler(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    subject: Subject,
    name: str,
    resource_type: str,
    risk: str,
    requires_approval: bool,
    fn: Callable[..., Awaitable[str]],
) -> Callable[..., Awaitable[str]]:
    engine = PolicyEngine(settings)
    metrics = get_metrics()

    async def handler(**kwargs: Any) -> str:
        resource = Resource(type=resource_type, id=name, kb_id=kwargs.get("kb_id"))
        decision = engine.evaluate(
            subject,
            name,
            resource,
            tool_risk=risk,
            tool_requires_approval=requires_approval,
        )
        await record_audit(
            session_factory,
            subject,
            name,
            resource,
            decision,
            detail={"args": {k: v for k, v in kwargs.items() if k != "kb_id"}},
        )
        if not decision.allowed:
            metrics.inc("policy_denied_total", {"tool": name})
            if decision.requires_approval:
                return f"APPROVAL_REQUIRED: {name} 属高风险动作，需审批后执行（{decision.reason}）。"
            return f"POLICY_DENIED: {name} 被策略拒绝（{decision.reason}）。"
        return await fn(**kwargs)

    return handler
