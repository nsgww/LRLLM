"""自动化评估接口预留（07-evaluation-spec 第 9 节）。

v0.1 不实现 Runner（10 第 10 条 Non-Negotiable）；本模块只固定契约，
后续实现不得破坏签名语义。Case 断言使用 Heading Path 等稳定标识，
不绑定易变的 chunk_id。
"""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class EvalFixture:
    knowledge_base: str
    documents: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EvalInput:
    query: str
    conversation: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class EvalExpect:
    retrieval: dict = field(default_factory=dict)
    answer: dict = field(default_factory=dict)
    evidence_status: str | None = None
    version_boundary: str | None = None


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    category: str
    input: EvalInput
    expect: EvalExpect
    fixture: EvalFixture | None = None


@dataclass
class CaseResult:
    case_id: str
    trace_id: str
    retrieval_scores: dict = field(default_factory=dict)
    answer_score: int | None = None  # 人工评分，自动化时为 None 待补
    grounded: bool | None = None
    passed: bool = False


class QueryTarget(Protocol):
    """EvalRunner 调用的 Query 入口。"""

    async def ask(self, knowledge_base_id: str, query: str) -> dict:
        ...


class EvalDataset(Protocol):
    def load(self, path: str) -> list[EvalCase]:
        ...


class EvalRunner(Protocol):
    async def run(self, cases: list[EvalCase], target: QueryTarget) -> "EvalReport":
        ...


class EvalReport(Protocol):
    case_results: list[CaseResult]
    metrics: dict  # recall@k / grounded_rate / ...

    def summary(self) -> dict:
        ...
