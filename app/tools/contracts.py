"""Agent 工具契约（Tool Router，01-architecture 第 9 节）。

设计原则
--------
工具是**纯业务函数**，不依赖 langchain。langchain 的 ``@tool`` 包装与
schema 转换放在 ``app/agent/adapters.py``，原因：

1. 业务逻辑与框架解耦：换掉 langchain 或直接由代码调用都不受影响。
2. 可测试性：测试工具行为不需要安装 langchain。
3. 延迟导入：未安装 langchain 时，本模块仍可被 /v1/query 路径安全导入。

安全约束（不可绕过）
-------------------
``knowledge_base_id`` 由工具的**构造参数**注入（闭包捕获），绝不来自
LLM 输出。工具收到的只有 query / product / version 这类语义参数，
因此 Agent 无论怎么决策都不可能越权访问其他知识库
（沿袭 06 第 3 节「scope never comes from LLM output」）。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolSpec:
    """一个工具的声明。

    ``name`` / ``description`` / ``parameters`` 会转成 LLM 可见的 function
    schema；``handler`` 是实际执行的异步函数。
    """

    name: str
    description: str
    # JSON Schema 形态的参数描述（OpenAI function calling 子集）
    parameters: dict[str, Any]
    handler: Callable[..., Awaitable[str]]


@dataclass
class ToolCallRecord:
    """一次工具调用的记录，写入 Trace 供回放与排障。"""

    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)
    # 工具返回值截断后的摘要：Trace 是审计用途，不存全量正文
    result_preview: str = ""
    error: str | None = None


# ---------------------------------------------------------------------------
# 工具返回值格式
# ---------------------------------------------------------------------------
# 工具统一返回「给 LLM 读的纯文本」。理由：LangChain 的 ToolMessage 需要
# 字符串；结构化数据在此处序列化为带标题的文本，比 JSON 更省 token 且
# LLM 更易引用。任何异常都收敛成带前缀的可读文本，而不是抛出——
# 工具失败应让 LLM 知道并自行决定下一步（换查询词 / 直接回答），
# 而不是把整个 Agent 循环打断。
ERROR_PREFIX = "TOOL_ERROR:"
