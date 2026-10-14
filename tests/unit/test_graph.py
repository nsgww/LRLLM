"""LangGraph 编排层测试（12-agent-platform-spec §2.2）。

用 fake chat model 驱动 StateGraph（消息用真实 langchain AIMessage，因为
MessagesState 的 add_messages reducer 只接受 langchain 消息类型），不连真实
LLM：验证事件序列、工具调用、迭代收敛与 MemorySaver checkpoint 可查询。
"""

from __future__ import annotations

import asyncio

from langchain_core.messages import AIMessage

from app.agent.graph import build_agent_graph, run_graph_events
from app.tools.contracts import ToolSpec


class _FakeModel:
    def __init__(self, script: list[AIMessage]):
        self._script = list(script)

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages, **kwargs):
        return self._script.pop(0) if self._script else AIMessage("兜底")


def _tool(name: str = "t") -> ToolSpec:
    async def handler(x):  # noqa: ANN001
        return "结果"

    return ToolSpec(
        name=name,
        description="d",
        parameters={
            "type": "object",
            "properties": {"x": {"type": "number"}},
            "required": ["x"],
        },
        handler=handler,
    )


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
    state = asyncio.run(
        graph.ainvoke(
            {
                "messages": [("human", "q")],
                "kb_id": "kb",
                "answer_id": "t1",
                "iterations": 0,
                "steps": [],
                "final_answer": "",
                "done": False,
            },
            config=cfg,
        )
    )
    assert state["done"] is True
    snap = graph.get_state(cfg)
    assert snap is not None
    assert snap.values.get("final_answer") == "ok"
