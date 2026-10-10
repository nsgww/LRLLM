"""LangChain ChatModel 工厂（Agent 路径专用）。

设计约束
--------
1. **延迟导入**：``langchain_openai`` 只在真正构造模型时导入。项目其余
   部分（/v1/query 固定管道）使用自研 ``httpx`` provider，未安装
   langchain 时不应受任何影响。因此本模块在 import 期不触碰 langchain。
2. **复用既有配置**：模型名 / API Key / base_url / timeout 全部来自
   ``Settings``，与自研 provider 保持同一套环境变量，不做第二套配置。
3. **保留 SSRF 防线**：base_url 的私网校验在 ``app.core.config`` 的
   field_validator 与 ``outbound_host_issues`` 中已完成，是在 settings
   实例化阶段拦下的，本工厂无需重复。
4. **可注入**：``build_chat_model`` 接受可选 ``model`` 覆盖，测试可传入
   fake/mock 对象而不触发 langchain 导入。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.config import Settings
from app.core.errors import AppError

if TYPE_CHECKING:  # 仅类型检查期，运行时不导入
    from langchain_core.language_models.chat_models import BaseChatModel


class LangChainUnavailableError(AppError):
    """langchain 未安装。属配置/环境问题，非用户输入错误。"""

    def __init__(self) -> None:
        super().__init__(
            code="AGENT_UNAVAILABLE",
            message=(
                "agent capability requires the optional 'langchain-core' and "
                "'langchain-openai' packages; install them with "
                "`pip install 'langchain-core>=0.3' 'langchain-openai>=0.2'`"
            ),
            http_status=503,
        )


def is_langchain_available() -> bool:
    """探测 langchain 是否可用，不抛异常。供 /health 或启动日志使用。"""
    try:
        import langchain_openai  # noqa: F401
    except ImportError:
        return False
    return True


def build_chat_model(
    settings: Settings,
    model: str | None = None,
    temperature: float | None = None,
) -> BaseChatModel:
    """按 Settings 构造一个 LangChain ChatModel（OpenAI 兼容端点）。

    ``model`` / ``temperature`` 可显式覆盖，方便测试与后续按场景切换。

    任何 endpoint 只要说 /chat/completions 协议即可：OpenAI、Azure 兼容
    网关、本地 vLLM / Ollama 都能用，与自研 provider 的兼容面一致。
    """
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:  # pragma: no cover - 取决于运行环境
        raise LangChainUnavailableError() from exc

    model_name = model or settings.llm_model
    if not model_name:
        raise AppError(
            code="LLM_NOT_CONFIGURED",
            message="RAG_LLM_MODEL is not set; agent requires an LLM model",
            http_status=503,
        )

    kwargs: dict[str, object] = {
        "model": model_name,
        "api_key": settings.llm_api_key or "not-needed",
        "timeout": settings.llm_timeout_seconds,
        "max_retries": settings.provider_max_attempts,
    }
    if settings.llm_base_url:
        kwargs["base_url"] = settings.llm_base_url
    if temperature is not None:
        kwargs["temperature"] = temperature

    return ChatOpenAI(**kwargs)
