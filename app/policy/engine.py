"""Policy Engine：身份 · 权限 · 风险等级 · 审批（12-agent-platform-spec §2.4）。

规则来自配置（``RAG_POLICY_*``），保持无状态、可单测。评估在工具执行前调用；
``high`` 风险动作默认需审批（非 admin），未审批即拒绝并交由上层记 Audit。
"""

from __future__ import annotations

from app.core.config import Settings
from app.policy.models import Decision, Resource, Subject

_HIGH = "high"


class PolicyEngine:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def evaluate(
        self,
        subject: Subject,
        action: str,
        resource: Resource,
        *,
        tool_risk: str = "low",
        tool_requires_approval: bool = False,
    ) -> Decision:
        risk = tool_risk or "low"

        # 高风险动作：admin 放行；非 admin 走"需审批 / 默认拒绝"策略。
        if risk == _HIGH and not subject.is_admin:
            if self._settings.policy_high_risk_requires_approval:
                return Decision(
                    allowed=False,
                    risk=risk,
                    requires_approval=True,
                    reason="high-risk action requires approval",
                )
            if self._settings.policy_default_deny_high_risk:
                return Decision(
                    allowed=False,
                    risk=risk,
                    reason="high-risk action denied by policy",
                )

        # 工具显式要求审批且非 admin：未获批的动作**不允许直接执行**，
        # 由执行闸口转成 APPROVAL_REQUIRED 文本反馈给 LLM（12 §2.3/§4）。
        needs_approval = bool(tool_requires_approval) and not subject.is_admin
        if needs_approval:
            return Decision(
                allowed=False,
                risk=risk,
                requires_approval=True,
                reason="requires approval before execution",
            )
        return Decision(allowed=True, risk=risk, requires_approval=False, reason="")
