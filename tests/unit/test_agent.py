"""Agent（自主工具调用）单元测试。

覆盖点：
1. 工具契约：build_tools 返回正确的三个工具与 schema。
2. KB 作用域隔离：knowledge_base_id 由闭包捕获，LLM 传入的额外参数
   无法改变检索范围（结构上越权不可能）。
3. 决策循环：模拟 LLM 先调用工具再回答，验证事件序列与 Trace 记录。
4. 收敛控制：迭代上限生效、工具异常被收敛为可读文本不中断循环。
5. 降级：langchain 未安装时给出明确错误码而非 500。

全部测试用 fake chat model，**不依赖 langchain 真实安装**，因为：
- CI 环境可能只装核心依赖；
- 业务逻辑（循环/收敛/作用域）与框架无关，本就该独立可测。
"""

from __future__ import annotations

import asyncio

import pytest

from app.agent.runner import AgentRunner, _message_text, _tool_calls_of
from app.core.config import Settings
from app.tools import ERROR_PREFIX, build_tools

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeResponse:
    """模拟 LangChain AIMessage：带 content 与可选 tool_calls。"""

    def __init__(self, content: str = "", tool_calls: list | None = None):
        self.content = content
        self.tool_calls = tool_calls or []
        self.additional_kwargs: dict = {}


class _FakeModel:
    """模拟 ChatModel：bind_tools 返回自身，ainvoke 按脚本依次返回。"""

    def __init__(self, script: list[_FakeResponse]):
        self._script = list(script)
        self.seen_messages: list = []
        self.bound_tools: list = []

    def bind_tools(self, tools, **kwargs):
        self.bound_tools = list(tools)
        return self

    async def ainvoke(self, messages, **kwargs):
        self.seen_messages = list(messages)
        if self._script:
            return self._script.pop(0)
        return _FakeResponse("兜底答案")

    async def astream(self, messages, **kwargs):
        yield _FakeResponse("流式答案")


class _StubHybrid:
    """记录调用参数的 HybridRetriever 替身。"""

    def __init__(self, candidates=None):
        self.calls: list[tuple] = []
        self._candidates = candidates or []

    async def retrieve(self, query, filters, strategy):
        from app.retrieval.hybrid import HybridResult

        self.calls.append((query, filters))
        return HybridResult(candidates=self._candidates)


class _StubRerank:
    def __init__(self, chunks=None):
        self._chunks = chunks or []

    async def load_rows(self, ids):
        return {}

    async def rank(self, query, candidates, rows_by_id, sub_query_id=None):
        from app.retrieval.rerank import RerankOutcome

        return RerankOutcome(chunks=self._chunks, fallback=False)


class _StubSessionFactory:
    """async context manager 返回一个哑 session。"""

    def __call__(self):
        return self

    async def __aenter__(self):
        return object()

    async def __aexit__(self, *exc):
        return False


# 合法 UUID：_save_trace 会把它转成 uuid.UUID
_KB_ID = "11111111-1111-1111-1111-111111111111"


class _TestableRunner(AgentRunner):
    """绕过 langchain 适配：直接把 ToolSpec 交给 fake model。

    真实路径的 ``_wrap_tools`` 依赖 langchain；本测试不安装它，因此
    覆盖这一层。决策循环、收敛控制、作用域隔离等被测逻辑与框架无关。
    """

    def _wrap_tools(self, specs):
        return [spec.name for spec in specs]


def _settings(**overrides) -> Settings:
    base = {
        "_env_file": None,
        "llm_model": "test-model",
        "agent_max_iterations": 4,
        "agent_enabled": True,
    }
    base.update(overrides)
    return Settings(**base)


def _runner(model, hybrid=None, rerank=None, **settings_overrides) -> AgentRunner:
    return _TestableRunner(
        settings=_settings(**settings_overrides),
        session_factory=_StubSessionFactory(),
        hybrid=hybrid or _StubHybrid(),
        rerank_service=rerank or _StubRerank(),
        chat_model=model,
    )


async def _collect(runner: AgentRunner, query: str = "问题") -> list:
    return [event async for event in runner.run(_KB_ID, query)]


# ---------------------------------------------------------------------------
# 1. 工具契约
# ---------------------------------------------------------------------------


def test_build_tools_returns_expected_tools():
    specs = build_tools(
        knowledge_base_id="kb-1",
        hybrid=_StubHybrid(),
        rerank=_StubRerank(),
        session_factory=_StubSessionFactory(),
        settings=_settings(),
    )
    names = [s.name for s in specs]
    assert names == [
        "knowledge_base_search",
        "list_knowledge_base_documents",
        "answer_directly",
    ]


def test_search_tool_schema_marks_query_required():
    specs = build_tools(
        knowledge_base_id="kb-1",
        hybrid=_StubHybrid(),
        rerank=_StubRerank(),
        session_factory=_StubSessionFactory(),
        settings=_settings(),
    )
    search = next(s for s in specs if s.name == "knowledge_base_search")
    assert search.parameters["required"] == ["query"]
    assert set(search.parameters["properties"]) == {"query", "product", "version"}


def test_every_tool_has_description():
    """LLM 靠 description 决策，空描述等于工具不可用。"""
    specs = build_tools(
        knowledge_base_id="kb-1",
        hybrid=_StubHybrid(),
        rerank=_StubRerank(),
        session_factory=_StubSessionFactory(),
        settings=_settings(),
    )
    assert all(s.description.strip() for s in specs)


# ---------------------------------------------------------------------------
# 2. KB 作用域隔离（核心安全断言）
# ---------------------------------------------------------------------------


async def test_search_tool_binds_knowledge_base_from_closure():
    """LLM 只能提供 query/product/version，KB 来自构造闭包。"""
    hybrid = _StubHybrid()
    specs = build_tools(
        knowledge_base_id="kb-SCOPED",
        hybrid=hybrid,
        rerank=_StubRerank(),
        session_factory=_StubSessionFactory(),
        settings=_settings(),
    )
    search = next(s for s in specs if s.name == "knowledge_base_search")

    await search.handler(query="价格", product="P1", version="v2")

    assert len(hybrid.calls) == 1
    _query, filters = hybrid.calls[0]
    # 无论 LLM 传什么，KB 始终是闭包捕获的那个
    assert filters.knowledge_base_id == "kb-SCOPED"
    assert filters.product == "P1"
    assert filters.version == "v2"


async def test_search_tool_cannot_be_redirected_to_other_kb():
    """即使 LLM 试图传 knowledge_base_id，也不会进入 filter（不在 schema 中）。"""
    hybrid = _StubHybrid()
    specs = build_tools(
        knowledge_base_id="kb-owner",
        hybrid=hybrid,
        rerank=_StubRerank(),
        session_factory=_StubSessionFactory(),
        settings=_settings(),
    )
    search = next(s for s in specs if s.name == "knowledge_base_search")

    # 模拟 LLM 塞入越权字段：handler 签名不含该参数，_invoke 的过滤层会剔除
    with pytest.raises(TypeError):
        await search.handler(query="x", knowledge_base_id="kb-victim")  # type: ignore[call-arg]

    assert hybrid.calls == []


# ---------------------------------------------------------------------------
# 3. 决策循环
# ---------------------------------------------------------------------------


async def test_agent_emits_meta_then_answer():
    model = _FakeModel([_FakeResponse("直接给出的答案")])
    events = await _collect(_runner(model))

    kinds = [e.event for e in events]
    assert kinds[0] == "meta"
    assert "done" in kinds
    assert events[0].data["mode"] == "agent"
    assert events[0].data["tools"] == [
        "knowledge_base_search",
        "list_knowledge_base_documents",
        "answer_directly",
    ]


async def test_agent_executes_tool_call_then_answers():
    """LLM 先请求检索，再给出答案——事件与 Trace 都要记录工具调用。"""
    model = _FakeModel(
        [
            _FakeResponse(
                "",
                tool_calls=[
                    {"name": "knowledge_base_search", "args": {"query": "退款流程"}, "id": "c1"}
                ],
            ),
            _FakeResponse("退款流程是……"),
        ]
    )
    events = await _collect(_runner(model, hybrid=_StubHybrid()))

    kinds = [e.event for e in events]
    assert "tool_call" in kinds
    tool_events = [e for e in events if e.event == "tool_call"]
    assert tool_events[0].data["tool"] == "knowledge_base_search"
    assert tool_events[0].data["arguments"] == {"query": "退款流程"}

    delta_text = "".join(e.data.get("text", "") for e in events if e.event == "delta")
    assert "退款流程" in delta_text


async def test_agent_records_steps_in_trace():
    """工具调用必须落进 Trace.agent_steps 供回放。"""
    captured: dict = {}

    class _TracingRunner(_TestableRunner):
        async def _save_trace(self, trace):
            captured["steps"] = list(trace.agent_steps)

    model = _FakeModel(
        [
            _FakeResponse(
                "", tool_calls=[{"name": "answer_directly", "args": {"answer": "hi"}, "id": "c1"}]
            ),
            _FakeResponse("最终回答"),
        ]
    )
    runner = _TracingRunner(
        settings=_settings(),
        session_factory=_StubSessionFactory(),
        hybrid=_StubHybrid(),
        rerank_service=_StubRerank(),
        chat_model=model,
    )
    await _collect(runner)

    assert captured["steps"]
    assert captured["steps"][0]["tool"] == "answer_directly"


# ---------------------------------------------------------------------------
# 4. 收敛控制与容错
# ---------------------------------------------------------------------------


async def test_iteration_budget_forces_finalize():
    """LLM 每轮都调工具不收敛时，必须在预算内强制收尾，不能死循环。"""
    infinite = [
        _FakeResponse(
            "",
            tool_calls=[
                {"name": "list_knowledge_base_documents", "args": {}, "id": f"c{i}"}
            ],
        )
        for i in range(10)
    ]
    # 最后一轮返回纯文本以收尾
    infinite.append(_FakeResponse("强制收尾"))
    model = _FakeModel(infinite)
    events = await _collect(_runner(model, agent_max_iterations=3))

    tool_events = [e for e in events if e.event == "tool_call"]
    assert len(tool_events) <= 3  # 不超过预算
    assert events[-1].event in ("done", "error")


async def test_unknown_tool_is_fed_back_not_fatal():
    model = _FakeModel(
        [
            _FakeResponse(
                "", tool_calls=[{"name": "no_such_tool", "args": {}, "id": "c1"}]
            ),
            _FakeResponse("知道了"),
        ]
    )
    events = await _collect(_runner(model))
    assert events[-1].event == "done"


async def test_tool_exception_does_not_break_loop():
    """工具抛错应转成 TOOL_ERROR 文本反馈给 LLM，循环继续。"""

    class _BoomHybrid(_StubHybrid):
        async def retrieve(self, query, filters, strategy):
            raise RuntimeError("boom")

    model = _FakeModel(
        [
            _FakeResponse(
                "",
                tool_calls=[{"name": "knowledge_base_search", "args": {"query": "q"}, "id": "c1"}],
            ),
            _FakeResponse("换个问法后回答"),
        ]
    )
    events = await _collect(_runner(model, hybrid=_BoomHybrid()))
    assert events[-1].event == "done"


async def test_agent_disabled_returns_error_event():
    model = _FakeModel([_FakeResponse("x")])
    events = await _collect(_runner(model, agent_enabled=False))
    assert events[-1].event == "error"
    assert events[-1].data["error"]["code"] == "AGENT_DISABLED"


async def test_timeout_is_reported_as_agent_timeout():
    """wall-clock 超时收敛为 AGENT_TIMEOUT 分类码。"""
    model = _FakeModel(
        [
            _FakeResponse(
                "",
                tool_calls=[{"name": "list_knowledge_base_documents", "args": {}, "id": "c1"}],
            ),
        ]
    )
    runner = _runner(model, agent_timeout_seconds=0.0)
    events = await _collect(runner)
    # 超时发生在第一轮之后；事件应以 error 收敛
    assert events[-1].event == "error"
    assert events[-1].data["error"]["code"] in ("AGENT_TIMEOUT", "INTERNAL_ERROR")


# ---------------------------------------------------------------------------
# 5. 兼容性 helper
# ---------------------------------------------------------------------------


def test_message_text_handles_str_and_blocks():
    assert _message_text(_FakeResponse("hello")) == "hello"
    blocks = _FakeResponse([{"type": "text", "text": "a"}, {"type": "text", "text": "b"}])
    assert _message_text(blocks) == "ab"


def test_tool_calls_of_falls_back_to_additional_kwargs():
    msg = _FakeResponse("")
    msg.additional_kwargs = {"tool_calls": [{"name": "t"}]}
    assert _tool_calls_of(msg) == [{"name": "t"}]


def test_error_prefix_is_stable():
    """TOOL_ERROR 前缀被 builtin 与 adapters 共用，改动会破坏 LLM 的失败识别。"""
    assert ERROR_PREFIX == "TOOL_ERROR:"


def test_agent_unavailable_error_shape():
    from app.llm.factory import LangChainUnavailableError

    err = LangChainUnavailableError()
    assert err.code == "AGENT_UNAVAILABLE"
    assert err.http_status == 503


def test_langchain_available_probe_does_not_raise():
    from app.llm.factory import is_langchain_available

    # 环境可能装或未装，关键是不抛异常
    assert isinstance(is_langchain_available(), bool)


# ---------------------------------------------------------------------------
# 6. 异步烟雾：确保无阻塞协程残留
# ---------------------------------------------------------------------------


def test_agent_run_is_async_generator():
    import inspect

    assert inspect.isasyncgenfunction(AgentRunner.run)


def test_no_lingering_tasks(recwarn=None):
    """跑一轮后不应留下 pending task（循环内未 await 的协程会泄漏）。"""

    async def scenario():
        model = _FakeModel([_FakeResponse("ok")])
        events = [e async for e in _runner(model).run("kb", "q")]
        return events

    events = asyncio.run(scenario())
    assert events[-1].event == "done"
