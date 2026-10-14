"""Business Tools 示例（12-agent-platform-spec §2.3）。

连"内部系统"的工具是风险敞口：handler 一律经 ``execute_with_policy`` 过
Policy + Audit。把 ``_internal_lookup`` / ``_internal_provision`` 换成真实
内部 API / 数据库调用即可，门控骨架不变。

装配方式：先声明 ToolSpec（handler=真实函数），再用 ``make_guarded_handler``
生成包闸口的 handler——闸口最终调用的是 spec.handler（真实函数），无循环。
"""

from __future__ import annotations

from typing import Any

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
    lookup_spec = ToolSpec(
        name="internal_lookup",
        description="查询内部系统数据（只读，medium 风险，直接放行）。",
        parameters={
            "type": "object",
            "properties": {"key": {"type": "string", "description": "查询键"}},
            "required": ["key"],
        },
        handler=_internal_lookup,
        risk_level="medium",
    )
    provision_spec = ToolSpec(
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
        handler=_internal_provision,
        risk_level="high",
        requires_approval=True,
    )

    def guarded(spec: ToolSpec) -> Any:
        return make_guarded_handler(
            session_factory=session_factory,
            settings=settings,
            subject=subject,
            spec=spec,
        )

    return [
        ToolSpec(
            name=lookup_spec.name,
            description=lookup_spec.description,
            parameters=lookup_spec.parameters,
            handler=guarded(lookup_spec),
            risk_level=lookup_spec.risk_level,
        ),
        ToolSpec(
            name=provision_spec.name,
            description=provision_spec.description,
            parameters=provision_spec.parameters,
            handler=guarded(provision_spec),
            risk_level=provision_spec.risk_level,
            requires_approval=True,
        ),
    ]
