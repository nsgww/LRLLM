"""LangGraph 编排层测试（12-agent-platform-spec §2.2）。

用 fake chat model 驱动 StateGraph（消息用真实 langchain AIMessage，因为
MessagesState 的 add_messages reducer 只接受 langchain 消息类型），不连真实
LLM：验证事件序列、工具调用、迭代收敛、MemorySaver checkpoint 与 Approval
（interrupt 挂起 + Command resume 恢复）。
"""

from __future__ import annotations

import asyncio

import pytest

# langchain / langgraph 是本项目的**可选**依赖（见 app/agent/graph.py 的延迟
# 导入设计）。缺失时必须让本模块整体 skip，而不是在 collection 阶段抛
# ModuleNotFoundError —— 那会中断整个测试套件，连不依赖 langchain 的用例
# 都跑不了。
pytest.importorskip("langchain_core")
pytest.importorskip("langgraph")

from langchain_core.messages import AIMessage

from app.agent.graph import (
    build_agent_graph,
    resume_graph,
    run_graph_events,
)
from app.tools.contracts import ToolSpec


class _FakeModel:
    def __init__(self, script: list[AIMessage]):
        self._script = list(script)

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages, **kwargs):
        return self._script.pop(0) if self._script else AIMessage("兜底")


def _tool(name: str = "t", requires_approval: bool = False, handler=None) -> ToolSpec:
    async def _default(x):
        return "结果"

    return ToolSpec(
        name=name,
        description="d",
        parameters={
            "type": "object",
            "properties": {"x": {"type": "number"}},
            "required": ["x"],
        },
        handler=handler or _default,
        risk_level="high" if requires_approval else "low",
        requires_approval=requires_approval,
    )


def _initial(answer_id: str, messages=None) -> dict:
    return {
        "messages": messages or [("human", "q")],
        "kb_id": "kb",
        "answer_id": answer_id,
        "iterations": 0,
        "steps": [],
        "final_answer": "",
        "done": False,
        "subject_is_admin": False,
        "approvals": [],
    }


async def _run(model, tools, max_iterations=3):
    graph = build_agent_graph(
        model_with_tools=model,
        tools_by_name={t.name: t for t in tools},
        max_iterations=max_iterations,
    )
    return [
        e
        async for e in run_graph_events(
            graph=graph,
            knowledge_base_id="kb",
            query="q",
            answer_id="a",
            tools=tools,
            max_iterations=max_iterations,
        )
    ]


async def test_graph_emits_meta_then_delta_done():
    events = await _run(_FakeModel([AIMessage("答案")]), [])
    kinds = [e.event for e in events]
    assert kinds[0] == "meta"
    assert kinds[-1] == "done"
    assert "delta" in kinds
    assert any(e.data.get("text") == "答案" for e in events if e.event == "delta")


async def test_graph_tool_then_answer():
    model = _FakeModel(
        [
            AIMessage("", tool_calls=[{"name": "t", "args": {"x": 1}, "id": "c1"}]),
            AIMessage("ans"),
        ]
    )
    events = await _run(model, [_tool()])
    assert "tool_call" in [e.event for e in events]
    assert any(e.data.get("tool") == "t" for e in events if e.event == "tool_call")
    assert "ans" in "".join(
        e.data.get("text", "") for e in events if e.event == "delta"
    )


async def test_graph_iteration_cap_forces_finalize():
    infinite = [
        AIMessage("", tool_calls=[{"name": "t", "args": {"x": 1}, "id": f"c{i}"}])
        for i in range(10)
    ]
    infinite.append(AIMessage("收尾"))
    events = await _run(_FakeModel(infinite), [_tool()], max_iterations=3)
    assert len([e for e in events if e.event == "tool_call"]) <= 3
    assert events[-1].event == "done"


def test_graph_checkpoint_queryable():
    graph = build_agent_graph(
        model_with_tools=_FakeModel([AIMessage("ok")]), tools_by_name={}, max_iterations=2
    )
    cfg = {"configurable": {"thread_id": "t1"}}
    state = asyncio.run(graph.ainvoke(_initial("t1"), config=cfg))
    assert state["done"] is True
    snap = graph.get_state(cfg)
    assert snap is not None
    assert snap.values.get("final_answer") == "ok"


# ---------------------------------------------------------------------------
# Approval：高风险工具 interrupt 挂起 + Command resume
# ---------------------------------------------------------------------------


async def test_approval_interrupt_then_denied_does_not_execute():
    executed: list = []

    async def handler(x):
        executed.append(x)
        return "已执行写操作"

    tool = _tool("provision", requires_approval=True, handler=handler)
    model = _FakeModel(
        [
            AIMessage("", tool_calls=[{"name": "provision", "args": {"x": 1}, "id": "c1"}]),
            AIMessage("完成"),
        ]
    )
    graph = build_agent_graph(
        model_with_tools=model, tools_by_name={"provision": tool}, max_iterations=3
    )
    cfg = {"configurable": {"thread_id": "appr-denied"}}

    await graph.ainvoke(_initial("appr-denied"), config=cfg)
    snap = graph.get_state(cfg)
    assert snap.next  # 挂在 interrupt，等待审批
    assert executed == []  # 未审批前不执行

    final = await resume_graph(graph=graph, thread_id="appr-denied", approved=False)
    assert executed == []  # 拒绝后仍不执行
    assert final["done"] is True


async def test_approval_resume_approved_executes():
    executed: list = []

    async def handler(x):
        executed.append(x)
        return "已执行写操作"

    tool = _tool("provision", requires_approval=True, handler=handler)
    model = _FakeModel(
        [
            AIMessage("", tool_calls=[{"name": "provision", "args": {"x": 1}, "id": "c1"}]),
            AIMessage("完成"),
        ]
    )
    graph = build_agent_graph(
        model_with_tools=model, tools_by_name={"provision": tool}, max_iterations=3
    )
    cfg = {"configurable": {"thread_id": "appr-ok"}}

    await graph.ainvoke(_initial("appr-ok"), config=cfg)
    assert graph.get_state(cfg).next  # 等待审批

    final = await resume_graph(graph=graph, thread_id="appr-ok", approved=True)
    assert executed == [1]  # 批准后执行
    assert final["done"] is True


async def test_approval_interrupt_does_not_replay_earlier_tool():
    """回归：resume 不得重复执行同批已完成的工具。

    LangGraph 恢复挂起时会**从头重跑整个节点**。若 interrupt 写在 act 的
    tool_calls 循环内，「低风险工具先执行 → 高风险工具挂起」再 resume，
    低风险工具会被执行两次（副作用翻倍）。审批隔离到无副作用的 approve
    节点后：审批前不执行任何工具，resume 后每个工具恰好执行一次。
    """
    read_calls: list = []
    write_calls: list = []

    async def read_handler(x):
        read_calls.append(x)
        return "读结果"

    async def write_handler(x):
        write_calls.append(x)
        return "写结果"

    read_tool = _tool("read_data", requires_approval=False, handler=read_handler)
    write_tool = _tool("provision", requires_approval=True, handler=write_handler)
    model = _FakeModel(
        [
            AIMessage(
                "",
                tool_calls=[
                    {"name": "read_data", "args": {"x": 1}, "id": "c1"},
                    {"name": "provision", "args": {"x": 2}, "id": "c2"},
                ],
            ),
            AIMessage("完成"),
        ]
    )
    graph = build_agent_graph(
        model_with_tools=model,
        tools_by_name={"read_data": read_tool, "provision": write_tool},
        max_iterations=3,
    )
    cfg = {"configurable": {"thread_id": "no-replay"}}
    await graph.ainvoke(_initial("no-replay"), config=cfg)

    assert graph.get_state(cfg).next  # 挂在审批
    assert read_calls == []  # 审批前一个工具都不执行（approve 节点无副作用）
    assert write_calls == []

    await resume_graph(graph=graph, thread_id="no-replay", approved=True)
    assert read_calls == [1]  # 恰好一次；旧实现此处会是 [1, 1]
    assert write_calls == [2]


async def test_high_risk_without_explicit_flag_still_requires_approval():
    """``risk_level="high"`` 但未设 ``requires_approval`` 也要弹审批。

    审批判定必须与 ``execute_with_policy`` 同源（PolicyEngine），否则会出现
    「闸口要求审批、图却不弹审批」的分叉：工具被静默拒绝而不是等人审。
    """
    from app.core.config import Settings
    from app.policy.models import Subject

    executed: list = []

    async def handler(x):
        executed.append(x)
        return "已执行"

    tool = ToolSpec(
        name="danger",
        description="d",
        parameters={
            "type": "object",
            "properties": {"x": {"type": "number"}},
            "required": ["x"],
        },
        handler=handler,
        risk_level="high",
        requires_approval=False,  # 只标风险等级，没显式要求审批
    )
    model = _FakeModel(
        [AIMessage("", tool_calls=[{"name": "danger", "args": {"x": 1}, "id": "c1"}])]
    )
    graph = build_agent_graph(
        model_with_tools=model,
        tools_by_name={"danger": tool},
        max_iterations=3,
        policy_ctx={
            "settings": Settings(_env_file=None, llm_model="m"),
            "subject": Subject(id="u1", roles=("user",)),
            "kb_id": "kb",
        },
    )
    cfg = {"configurable": {"thread_id": "risk-high"}}
    await graph.ainvoke(_initial("risk-high"), config=cfg)

    assert graph.get_state(cfg).next  # 挂在审批，而不是直接执行
    assert executed == []


async def test_run_graph_emits_approval_required_on_interrupt():
    async def handler(x):
        return "已执行"

    tool = _tool("provision", requires_approval=True, handler=handler)
    model = _FakeModel(
        [AIMessage("", tool_calls=[{"name": "provision", "args": {"x": 1}, "id": "c1"}])]
    )
    graph = build_agent_graph(
        model_with_tools=model, tools_by_name={"provision": tool}, max_iterations=3
    )
    events = [
        e
        async for e in run_graph_events(
            graph=graph,
            knowledge_base_id="kb",
            query="q",
            answer_id="appr-sse",
            tools=[tool],
            max_iterations=3,
        )
    ]
    kinds = [e.event for e in events]
    assert "approval_required" in kinds
    assert kinds[-1] == "approval_required"  # 挂起，不产 done


# ---------------------------------------------------------------------------
# runner 的 use_graph 分支（端点切换，12 §2.2）：RAG_AGENT_USE_GRAPH 走 LangGraph 图
# ---------------------------------------------------------------------------

from app.agent.runner import AgentRunner
from app.core.config import Settings


class _StubHybrid:
    async def retrieve(self, query, filters, strategy):
        from app.retrieval.hybrid import HybridResult

        return HybridResult(candidates=[])


class _StubRerank:
    async def load_rows(self, ids):
        return {}

    async def rank(self, query, candidates, rows_by_id, sub_query_id=None):
        from app.retrieval.rerank import RerankOutcome

        return RerankOutcome(chunks=[], fallback=False)


class _StubSF:
    def __call__(self):
        return self

    async def __aenter__(self):
        return object()

    async def __aexit__(self, *exc):
        return False


class _AIModel:
    """bind_tools 返回自身 + ainvoke 返回 AIMessage（graph 的 add_messages 需要）。"""

    def __init__(self, script):
        self._script = list(script)

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages, **kwargs):
        return self._script.pop(0) if self._script else AIMessage("兜底")


class _GraphRunner(AgentRunner):
    def _wrap_tools(self, specs):
        return [s.name for s in specs]

    async def _conversation_setup(self, knowledge_base_id, query, conversation_id):
        return conversation_id or knowledge_base_id, ""

    async def _persist(self, *args):
        return None

    async def _save_trace(self, trace):
        return None


def _graph_runner(model, use_graph):
    return _GraphRunner(
        settings=Settings(
            _env_file=None,
            llm_model="m",
            agent_max_iterations=3,
            agent_enabled=True,
            agent_use_graph=use_graph,
        ),
        session_factory=_StubSF(),
        hybrid=_StubHybrid(),
        rerank_service=_StubRerank(),
        chat_model=model,
    )


async def test_runner_use_graph_emits_meta_delta_done():
    events = [
        e
        async for e in _graph_runner(_AIModel([AIMessage("图答案")]), use_graph=True).run(
            "kb", "q"
        )
    ]
    kinds = [e.event for e in events]
    assert kinds[0] == "meta"
    assert kinds[-1] == "done"
    assert any(e.data.get("text") == "图答案" for e in events if e.event == "delta")


async def test_runner_default_uses_loop_still_done():
    # 默认(use_graph=False)走手写 _loop，行为不变（零回归）。
    events = [
        e
        async for e in _graph_runner(
            _AIModel([AIMessage("loop答案")]), use_graph=False
        ).run("kb", "q")
    ]
    assert events[-1].event == "done"
