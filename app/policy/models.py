"""Policy Engine 领域模型（12-agent-platform-spec §2.4）。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Subject:
    """身份主体：谁在发起动作。无鉴权时默认 anonymous/user。"""

    id: str
    roles: tuple[str, ...] = ()

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles


@dataclass(frozen=True)
class Resource:
    """被访问的资源（用于审计与策略判定）。"""

    type: str  # "knowledge_base" | "wiki_page" | "tool" | ...
    id: str | None = None
    kb_id: str | None = None


@dataclass(frozen=True)
class Decision:
    """策略评估结果。"""

    allowed: bool
    risk: str = "low"  # low | medium | high
    requires_approval: bool = False
    reason: str = ""


ANONYMOUS = Subject(id="anonymous", roles=("user",))
