"""Business Tools 示例（12-agent-platform-spec §2.3）。

连"内部系统"的工具是风险敞口，执行前经 ``make_guarded_handler`` 过
Policy + Audit。把 ``_internal_lookup`` / ``_internal_provision`` 换成真实
内部 API / 数据库调用即可，门控骨架不变。

- ``internal_lookup``：只读内部查询，medium 风险，放行。
- ``internal_provision``：业务系统写操作，high 风险 + 需审批；非 admin
  默认返回 APPROVAL_REQUIRED / POLICY_DENIED 且不执行。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.policy.models import Subject
from app.tools.contracts import ToolSpec
from app.tools.gate import make_guarded_handler


async def _internal_lookup(key: str) -> str:
    # 占位：真实实现调用内部 API / 数据库
    return f"[内部数据] {key} -> OK（示例）"


async def _internal_provision(resource: str, size: str) -> str:
    # 占位：真实实现对业务系统执行写操作
    return f"[内部操作] 已对 {resource} 执行 provision(size={size})（示例）"


def build_business_tools(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    subject: Subject,
) -> list[ToolSpec]:
    """构造带 Policy 门控的业务工具集（按身份主体生效）。"""
    lookup = make_guarded_handler(
        session_factory=session_factory,
        settings=settings,
        subject=subject,
        name="internal_lookup",
        resource_type="internal_api",
        risk="medium",
        requires_approval=False,
        fn=_internal_lookup,
    )
    provision = make_guarded_handler(
        session_factory=session_factory,
        settings=settings,
        subject=subject,
        name="internal_provision",
        resource_type="business_system",
        risk="high",
        requires_approval=True,
        fn=_internal_provision,
    )
    return [
        ToolSpec(
            name="internal_lookup",
            description="查询内部系统数据（只读，medium 风险，直接放行）。",
            parameters={
                "type": "object",
                "properties": {"key": {"type": "string", "description": "查询键"}},
                "required": ["key"],
            },
            handler=lookup,
            risk_level="medium",
        ),
        ToolSpec(
            name="internal_provision",
            description="对业务系统执行 provisioning 写操作（high 风险，需审批）。",
            parameters={
                "type": "object",
                "properties": {
                    "resource": {"type": "string"},
                    "size": {"type": "string"},
                },
                "required": ["resource", "size"],
            },
            handler=provision,
            risk_level="high",
            requires_approval=True,
        ),
    ]
