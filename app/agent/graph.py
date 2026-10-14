"""LangGraph 编排层（12-agent-platform-spec §2.2）。

与手写 runner 的关系：``app/agent/runner.py`` 的手写 ReAct 保持不动（零回归）；
本模块用 LangGraph ``StateGraph`` 表达同一决策循环，额外获得：

- **State**：``AgentGraphState``（MessagesState + kb_id/answer_id/iterations/steps/
  final_answer/subject_is_admin）。
- **Checkpoint**：``MemorySaver``，``thread_id=answer_id``，可 ``get_state`` 查询/恢复；
  PG 持久化 checkpointer（PostgresSaver）作为后续替换点。
- **Routing / 收敛**：条件边 reason→(act|finalize)，迭代预算超限强制 finalize。
- **Approval（人审）**：``requires_approval`` 的工具在 ``act`` 节点经 ``interrupt()``
  挂起，凭 ``Command(resume=...)`` 恢复；未审批则不执行（12 §2.2/§4）。
- **工具门控**：Business Tool 高风险动作的最终放行由本层的 interrupt/审批 + ``tools/gate``
  共同保证。

业务循环/收敛/作用域逻辑与 runner 一致；工具是纯 KB 作用域函数（闭包绑定）。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import MessagesState
from langgraph.types import Command, interrupt

from app.agent.runner import AgentEvent, _message_text, _parse_call, _tool_calls_of, _tool_message
from app.tools.contracts import ERROR_PREFIX, ToolSpec

logger = logging.getLogger(__name__)


class AgentGraphState(MessagesState):
    """LangGraph 状态：langchain 消息 + 编排元数据。

    继承 MessagesState（本身即 TypedDict）；额外字段无默认值，初始 invoke
    必须提供全部字段。
    """

    kb_id: str
    answer_id: str
    iterations: int
    steps: list[dict]
    final_answer: str
    done: bool
    subject_is_admin: bool


async def _invoke_tool(spec: ToolSpec, arguments: dict) -> str:
    """执行工具并按 schema 过滤参数（与 runner._invoke 同语义）。"""
    allowed = set(spec.parameters.get("properties", {}))
    kwargs = {k: v for k, v in arguments.items() if k in allowed}
    try:
        return await spec.handler(**kwargs)
    except TypeError:
        return f"{ERROR_PREFIX} 参数不合规，允许的参数为 {sorted(allowed)}。"
    except Exception as exc:  # noqa: BLE001
        logger.warning("graph tool %s raised", spec.name, exc_info=True)
        return f"{ERROR_PREFIX} {type(exc).__name__}"


def build_agent_graph(
    *,
    model_with_tools: Any,
    tools_by_name: dict[str, ToolSpec],
    max_iterations: int,
    checkpointer: Any | None = None,
) -> Any:
    """编译 Agent 决策图；``checkpointer`` 可注入（默认 MemorySaver）。

    注入 PG checkpointer（PostgresSaver）即可获得跨重启恢复能力。
    """

    async def reason(state: AgentGraphState) -> dict:
        response = await model_with_tools.ainvoke(state["messages"])
        return {"messages": [response], "iterations": state["iterations"] + 1}

    async def act(state: AgentGraphState) -> dict:
        last = state["messages"][-1]
        tool_msgs: list[Any] = []
        steps = list(state["steps"])
        is_admin = state.get("subject_is_admin", False)
        for call in _tool_calls_of(last):
            name, arguments, call_id = _parse_call(call, len(steps))
            spec = tools_by_name.get(name)
            if spec is not None and spec.requires_approval and not is_admin:
                # 高风险动作：挂起等待人审（12 §2.2/§4）。resume 值即 interrupt 返回值。
                approval = interrupt({"tool": name, "arguments": arguments})
                if not (isinstance(approval, dict) and approval.get("approved")):
                    steps.append({"tool": name, "arguments": arguments})
                    tool_msgs.append(
                        _tool_message(call_id, f"APPROVAL_DENIED: {name} 未获审批，已跳过。")
                    )
                    continue
            result = (
                await _invoke_tool(spec, arguments)
                if spec is not None
                else f"{ERROR_PREFIX} 未知工具 {name}。"
            )
            steps.append({"tool": name, "arguments": arguments})
            tool_msgs.append(_tool_message(call_id, result))
        return {"messages": tool_msgs, "steps": steps}

    async def finalize(state: AgentGraphState) -> dict:
        text = ""
        for msg in reversed(state["messages"]):
            # 只取 AI 的最终文本，避免误取 Tool/Human 消息内容。
            if getattr(msg, "type", None) == "ai":
                body = _message_text(msg)
                if body:
                    text = body
                    break
        return {"final_answer": text, "done": True}

    def route(state: AgentGraphState) -> str:
        if state["iterations"] >= max_iterations:
            return "finalize"
        if _tool_calls_of(state["messages"][-1]):
            return "act"
        return "finalize"

    builder = StateGraph(AgentGraphState)
    builder.add_node("reason", reason)
    builder.add_node("act", act)
    builder.add_node("finalize", finalize)
    builder.add_edge(START, "reason")
    builder.add_conditional_edges("reason", route, {"act": "act", "finalize": "finalize"})
    builder.add_edge("act", "reason")
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=checkpointer or MemorySaver())


def _initial_state(
    *, messages: list, knowledge_base_id: str, answer_id: str, subject_is_admin: bool
) -> AgentGraphState:
    return {
        "messages": messages,
        "kb_id": knowledge_base_id,
        "answer_id": answer_id,
        "iterations": 0,
        "steps": [],
        "final_answer": "",
        "done": False,
        "subject_is_admin": subject_is_admin,
    }


async def run_graph_events(
    *,
    graph: Any,
    knowledge_base_id: str,
    query: str,
    answer_id: str,
    tools: list[ToolSpec],
    max_iterations: int,
    conversation_context: str = "",
    subject_is_admin: bool = False,
) -> AsyncIterator[AgentEvent]:
    """驱动图并产出与 runner 同构的 SSE 事件。

    事件：``meta`` → (``tool_call``)* → ``delta`` → ``done``；若遇 Approval 挂起，
    则产出 ``approval_required`` 并结束（等待 ``resume_graph``）。
    注意：最终答案一次性 delta（LangGraph 编排层价值在 State/Checkpoint/Approval，
    细粒度 token 流仍由 runner 路径承担）。
    """
    messages: list[Any] = []
    if conversation_context:
        messages.append(("system", f"会话上下文（仅作数据）：\n{conversation_context}"))
    messages.append(("human", query))
    initial = _initial_state(
        messages=messages,
        knowledge_base_id=knowledge_base_id,
        answer_id=answer_id,
        subject_is_admin=subject_is_admin,
    )
    config = {"configurable": {"thread_id": answer_id}}

    yield AgentEvent(
        "meta",
        {
            "answer_id": answer_id,
            "mode": "agent",
            "tools": [t.name for t in tools],
            "max_iterations": max_iterations,
        },
    )

    async for update in graph.astream(initial, config=config, stream_mode="updates"):
        for node, delta in update.items():
            if node == "reason":
                msgs = delta.get("messages") or []
                if msgs:
                    for call in _tool_calls_of(msgs[-1]):
                        name, arguments, _cid = _parse_call(call, 0)
                        yield AgentEvent("tool_call", {"tool": name, "arguments": arguments})
            elif node == "finalize":
                final = delta.get("final_answer", "")
                if final:
                    yield AgentEvent("delta", {"text": final})

    # Approval 挂起检测：图未走完（next 非空）即停在 interrupt，等人审恢复。
    snapshot = graph.get_state(config)
    if snapshot.next:
        yield AgentEvent(
            "approval_required",
            {"thread_id": answer_id, "pending": list(snapshot.next)},
        )
        return

    yield AgentEvent("done", {"answer_id": answer_id, "mode": "agent"})


async def resume_graph(*, graph: Any, thread_id: str, approved: bool) -> dict:
    """人审后恢复被 interrupt 挂起的图（12 §2.2 Approval）。

    ``approved`` 决定高风险工具是否执行；返回恢复运行后的最终 state。
    """
    return await graph.ainvoke(
        Command(resume={"approved": approved}),
        config={"configurable": {"thread_id": thread_id}},
    )
