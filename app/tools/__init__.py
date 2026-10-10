"""Tool Router（01-architecture 第 9 节）。

Agent 自主决策时可供调用的工具集。工具是纯业务函数，不依赖 langchain；
框架适配（``@tool`` 包装、schema 转换）在 ``app/agent/adapters.py``。

模块结构：
- ``contracts``：``ToolSpec`` / ``ToolCallRecord`` 等契约类型
- ``builtin``：知识库检索 / 元数据查询 / 直接回答三个内置工具

对称入口：``app.agent.runner.AgentRunner``。
"""

from app.tools.builtin import build_tools
from app.tools.contracts import ERROR_PREFIX, ToolCallRecord, ToolSpec

__all__ = ["ERROR_PREFIX", "ToolCallRecord", "ToolSpec", "build_tools"]
