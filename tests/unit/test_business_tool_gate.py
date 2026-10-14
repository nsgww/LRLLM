"""Business Tool 门控测试（12 §2.3/§2.4）：Policy + Audit 端到端。"""

import asyncio

from app.core.config import Settings
from app.policy.models import Subject
from app.tools.business import build_business_tools


class _FakeSession:
    def __init__(self) -> None:
        self.added: list = []

    def add(self, row) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None


def _sf():
    session = _FakeSession()
    return (lambda: session), session


def _tool(tools, name: str):
    return next(t for t in tools if t.name == name)


def test_internal_lookup_medium_allowed_and_audited():
    sf, session = _sf()
    tools = build_business_tools(
        session_factory=sf,
        settings=Settings(),
        subject=Subject("alice", ("user",)),
    )
    result = asyncio.run(_tool(tools, "internal_lookup").handler(key="k"))
    assert "[内部数据] k -> OK" in result
    assert len(session.added) == 1  # 审计已写入


def test_internal_provision_high_non_admin_requires_approval():
    sf, session = _sf()
    tools = build_business_tools(
        session_factory=sf,
        settings=Settings(),
        subject=Subject("alice", ("user",)),
    )
    result = asyncio.run(
        _tool(tools, "internal_provision").handler(resource="r", size="s")
    )
    assert result.startswith("APPROVAL_REQUIRED")
    assert "[内部操作]" not in result  # 未执行业务函数
    assert len(session.added) == 1


def test_internal_provision_admin_allowed():
    sf, session = _sf()
    tools = build_business_tools(
        session_factory=sf,
        settings=Settings(),
        subject=Subject("root", ("admin",)),
    )
    result = asyncio.run(
        _tool(tools, "internal_provision").handler(resource="r", size="s")
    )
    assert "[内部操作]" in result
    assert len(session.added) == 1
