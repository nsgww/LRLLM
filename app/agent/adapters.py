"""LangChain 适配层：把纯业务 ``ToolSpec`` 转成 langchain Tool。

本模块**只在 Agent 路径导入**，且 langchain 相关 import 全部在函数内部
（延迟导入）。未安装 langchain 时，import 本模块不会报错，只有真正调用
``to_langchain_tools`` 才会抛 ``LangChainUnavailableError``。

这样保证：/v1/query 等既有路径即使没装 langchain 也完全正常。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from app.llm.factory import LangChainUnavailableError
from app.tools.contracts import ToolSpec

if TYPE_CHECKING:  # 仅类型检查期
    from langchain_core.tools import BaseTool


def to_langchain_tools(specs: Sequence[ToolSpec]) -> list[BaseTool]:
    """把 ToolSpec 列表转成 langchain 可绑定的工具列表。

    使用 ``StructuredTool`` 手工构造而非 ``@tool`` 装饰器：我们的 handler
    是异步函数且参数 schema 已是 JSON Schema 形态，手工构造更直接，也避免
    依赖装饰器的 docstring 解析行为（会随版本变化）。
    """
    try:
        from langchain_core.tools import StructuredTool
    except ImportError as exc:  # pragma: no cover - 取决于运行环境
        raise LangChainUnavailableError() from exc

    tools: list[BaseTool] = []
    for spec in specs:
        tools.append(
            StructuredTool.from_function(
                coroutine=spec.handler,
                name=spec.name,
                description=spec.description,
                args_schema=_schema_for(spec),
            )
        )
    return tools


def _schema_for(spec: ToolSpec) -> type:
    """由 JSON Schema 动态生成 pydantic 模型，供 StructuredTool 使用。"""
    try:
        from pydantic import create_model
    except ImportError as exc:  # pragma: no cover - pydantic 是核心依赖
        raise LangChainUnavailableError() from exc

    properties: dict[str, Any] = spec.parameters.get("properties", {})
    required: set[str] = set(spec.parameters.get("required", []))
    fields: dict[str, Any] = {}
    for name, meta in properties.items():
        annotation = _annotation(meta.get("type", "string"))
        default = ... if name in required else None
        fields[name] = (annotation | None if default is None else annotation, default)
    if not fields:
        # StructuredTool 不接受空 schema 的模型类型；用空模型占位
        return create_model(f"{_model_name(spec)}Args")  # type: ignore[call-overload]
    return create_model(f"{_model_name(spec)}Args", **fields)  # type: ignore[call-overload]


def _annotation(json_type: str) -> type:
    return {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }.get(json_type, str)


def _model_name(spec: ToolSpec) -> str:
    """pydantic 模型名需为合法标识符：工具名转 PascalCase。"""
    parts = [p for p in spec.name.replace("-", "_").split("_") if p]
    return "".join(p[:1].upper() + p[1:] for p in parts) or "Tool"


def tool_call_record(tool: str, arguments: dict[str, Any], result: str) -> dict[str, Any]:
    """构造可 JSON 序列化的工具调用记录（供 Trace 存储）。

    结果截断到 500 字符：Trace 是审计与回放用途，不承载全量正文。
    """
    return {
        "tool": tool,
        "arguments": arguments,
        "result_preview": result[:500],
    }


def safe_parse_arguments(raw: Any) -> dict[str, Any]:
    """兼容不同版本 tool_call 的 arguments 形态（dict 或 JSON 字符串）。"""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {"_raw": raw}
        return parsed if isinstance(parsed, dict) else {"_value": parsed}
    return {}
