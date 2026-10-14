"""Policy Engine 契约测试（12-agent-platform-spec §2.4）。"""

from app.core.config import Settings
from app.policy import PolicyEngine
from app.policy.models import Resource, Subject


def _eval(settings: Settings, subject: Subject, **kw):
    engine = PolicyEngine(settings)
    return engine.evaluate(
        subject, kw.pop("action", "act"), Resource(type=kw.pop("rtype", "tool")), **kw
    )


def test_high_risk_non_admin_requires_approval():
    d = _eval(
        Settings(),
        Subject("a", ("user",)),
        tool_risk="high",
        tool_requires_approval=True,
    )
    assert d.allowed is False
    assert d.requires_approval is True
    assert d.risk == "high"


def test_high_risk_admin_allowed():
    d = _eval(
        Settings(),
        Subject("root", ("admin",)),
        tool_risk="high",
        tool_requires_approval=True,
    )
    assert d.allowed is True
    assert d.requires_approval is False


def test_high_risk_denied_when_approval_off_and_deny_on():
    d = _eval(
        Settings(
            policy_high_risk_requires_approval=False,
            policy_default_deny_high_risk=True,
        ),
        Subject("a", ("user",)),
        tool_risk="high",
    )
    assert d.allowed is False
    assert d.requires_approval is False


def test_medium_allowed_without_approval():
    d = _eval(Settings(), Subject("a", ("user",)), tool_risk="medium")
    assert d.allowed is True
    assert d.requires_approval is False


def test_tool_requires_approval_non_admin_flags_approval():
    d = _eval(
        Settings(),
        Subject("a", ("user",)),
        tool_risk="low",
        tool_requires_approval=True,
    )
    assert d.allowed is True
    assert d.requires_approval is True


def test_admin_bypasses_tool_approval():
    d = _eval(
        Settings(),
        Subject("root", ("admin",)),
        tool_risk="low",
        tool_requires_approval=True,
    )
    assert d.allowed is True
    assert d.requires_approval is False
