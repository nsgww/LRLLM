"""Policy + Audit 统一执行闸口（12-agent-platform-spec §2.3/§2.4）。

所有工具执行路径（手写 runner、LangGraph 图、Business Tools）都必须经过
``execute_with_policy``：PolicyEngine 评估 → 审计（高风险 fail-closed）→
拒绝则不执行。工具 handler 的真实调用只发生在 ``invoke_spec_handler``，
使"执行前必经策略门控"在结构上成立，而非依赖调用方自觉。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.observability.metrics import get_metrics
from app.policy import PolicyEngine
from app.policy.models import ANONYMOUS, Resource, Subject
from app.tools.contracts import ERROR_PREFIX, ToolSpec
from app.tracing.audit import record_audit

logger = logging.getLogger(__name__)


def _safe_args(arguments: dict[str, Any], limit: int = 2000) -> dict[str, str]:
    """LLM 参数截断后入审计 detail，避免大 payload 撑爆 JSONB。"""
    try:
        text = json.dumps(arguments, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(arguments)
    if len(text) > limit:
        text = text[:limit] + "...(truncated)"
    return {"args": text}


async def invoke_spec_handler(spec: Any, arguments: dict[str, Any]) -> str:
    """按 schema 过滤参数后调用工具 handler（全项目唯一的 handler 调用点）。"""
    allowed = set(spec.parameters.get("properties", {}))
    kwargs = {k: v for k, v in arguments.items() if k in allowed}
    try:
        return await spec.handler(**kwargs)
    except TypeError:
        return f"{ERROR_PREFIX} 参数不合规，允许的参数为 {sorted(allowed)}。"
    except Exception as exc:  # noqa: BLE001
        logger.warning("tool %s raised", spec.name, exc_info=True)
        return f"{ERROR_PREFIX} {type(exc).__name__}"


async def execute_with_policy(
    *,
    spec: Any,
    arguments: dict[str, Any],
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    subject: Subject | None = None,
    kb_id: str | None = None,
) -> str:
    """工具执行唯一闸口：评估 → 审计 → 拒绝或执行。

    - 拒绝（含需审批未批）：**不执行**，返回可读文本反馈给 LLM（12 §2.3）。
    - 审计：非低风险或被拒的调用写 audit_logs；审计失败时高风险动作
      fail-closed（拒绝执行）并计数（12 §2.5 审计完整性）。
    """
    engine = PolicyEngine(settings)
    metrics = get_metrics()
    subj = subject or ANONYMOUS
    resource = Resource(type="tool", id=spec.name, kb_id=kb_id)
    decision = engine.evaluate(
        subj,
        spec.name,
        resource,
        tool_risk=getattr(spec, "risk_level", "low"),
        tool_requires_approval=bool(getattr(spec, "requires_approval", False)),
    )

    audited = True
    if decision.risk != "low" or not decision.allowed:
        audited = await record_audit(
            session_factory,
            subj,
            spec.name,
            resource,
            decision,
            detail=_safe_args(arguments),
        )

    if not decision.allowed:
        metrics.inc("policy_denied_total", {"tool": spec.name})
        if decision.requires_approval:
            return (
                f"APPROVAL_REQUIRED: {spec.name} 属高风险动作，需人工审批后执行，"
                f"本次未执行。请向用户说明需先获得审批。"
            )
        return f"POLICY_DENIED: {spec.name} 被策略拒绝（{decision.reason}）。"

    if not audited and decision.risk == "high":
        metrics.inc("audit_write_failed_total")
        return f"POLICY_DENIED: 审计暂不可用，{spec.name}（高风险）已阻止执行。"

    return await invoke_spec_handler(spec, arguments)


def make_guarded_handler(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    subject: Subject,
    spec: ToolSpec,
) -> Any:
    """把 ToolSpec 的执行包进统一闸口（Business Tools 装配用）。

    返回的 handler 即 ToolSpec.handler：闸口内部最终调用的是 ``spec.handler``
    本身，因此无循环调用。
    """
    spec_shim = SimpleNamespaceLike(
        name=spec.name,
        parameters=spec.parameters,
        risk_level=spec.risk_level,
        requires_approval=spec.requires_approval,
        handler=spec.handler,
    )

    async def handler(**kwargs: Any) -> str:
        return await execute_with_policy(
            spec=spec_shim,
            arguments=kwargs,
            settings=settings,
            session_factory=session_factory,
            subject=subject,
        )

    return handler


class SimpleNamespaceLike:
    """闸口所需的 spec 最小协议（name/parameters/risk_level/requires_approval/handler）。"""

    __slots__ = ("name", "parameters", "risk_level", "requires_approval", "handler")

    def __init__(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)
