"""Agent（自主工具调用）能力。

让 LLM 自己决定下一步做什么：是否检索、检索什么、要不要重试、还是直接
回答。补齐 02 第 7 节预留但 v0.1 未实现的 ``Intent.TOOL_ACTION`` 形态。

- ``runner``：决策循环（``AgentRunner``）
- ``adapters``：langchain 适配层（延迟导入，未装 langchain 不影响主管道）

对外入口是 ``/v1/agent`` 端点，与 ``/v1/query`` 并存。
"""

from app.agent.runner import AGENT_STAGE, AgentEvent, AgentRunner

__all__ = ["AGENT_STAGE", "AgentEvent", "AgentRunner"]
