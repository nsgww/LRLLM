"""LangGraph 编排层测试（12-agent-platform-spec §2.2）。

用 fake chat model 驱动 StateGraph（消息用真实 langchain AIMessage，因为
MessagesState 的 add_messages reducer 只接受 langchain 消息类型），不连真实
LLM：验证事件序列、工具调用、迭代收敛、MemorySaver checkpoint 与 Approval
（interrupt 挂起 + Command resume 恢复）。
"""

from __future__ import annotations

import asyncio

from langchain_core.messages import AIMessage

from app.agent.graph import build_agent_graph, resume_graph, run_graph_events
from app.tools.contracts import ToolSpec


class _FakeModel:
    def __init__(self, script: list[AIMessage]):
        self._script = list(script)

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages, **kwargs):
        return self._script.pop(0) if self._script else AIMessage("兜底")


def _tool(name: str = "t", requires_approval: bool = False, handler=None) -> ToolSpec:
    async def _default(x):  # noqa: ANN001
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

    async def handler(x):  # noqa: ANN001
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

    async def handler(x):  # noqa: ANN001
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


async def test_run_graph_emits_approval_required_on_interrupt():
    async def handler(x):  # noqa: ANN001
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
