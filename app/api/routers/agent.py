"""Agent 端点：LLM 自主决策 + 工具调用（SSE 流式）。

与 ``/v1/query`` 的关系
-----------------------
- ``/v1/query``：确定性管道，行为可精确预测与回放，适合常规问答。
- ``/v1/agent``：由 LLM 自行决定检索/重试/收尾，适合探索性问题或多跳
  检索。两者并存，共享同一套 SSE 事件编码与知识库作用域契约。

事件序列
--------
``meta`` → (``tool_call``)* → ``delta``* → ``done``，异常走 ``error``。

额外事件 ``tool_call`` 让前端能展示「Agent 正在做什么」，这是自主决策
路径特有的可观测性产物，固定管道不会发出。

并发保护
--------
使用**独立信号量**（``agent_semaphore``）：Agent 单次请求的最坏外部调用数
远高于固定管道（每次迭代都可能检索 + 最终生成），若与 /v1/query 共享闸门
会互相拖累。独立闸门让两边的容量可分别调优。
"""

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.agent.runner import AgentEvent
from app.api.deps import require_api_key, require_kb_id
from app.api.schemas import AgentRequest
from app.core.config import get_settings
from app.core.errors import AppError

router = APIRouter(tags=["agent"], dependencies=[Depends(require_api_key)])

_HEARTBEAT_SECONDS = 15.0
_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/agent")
async def agent(
    body: AgentRequest,
    request: Request,
    kb_id: str = Depends(require_kb_id),
) -> StreamingResponse:
    settings = get_settings()
    await request.app.state.kb_service.get(kb_id)  # 404 when missing/deleted

    if not settings.agent_enabled:
        raise AppError(
            code="AGENT_DISABLED",
            message="agent capability is disabled (RAG_AGENT_ENABLED=false)",
            http_status=503,
        )
    if not request.app.state.agent_runner_available:
        # langchain 未安装：给出可操作的安装提示，而不是 500
        raise AppError(
            code="AGENT_UNAVAILABLE",
            message=(
                "agent capability requires 'langchain-core' and 'langchain-openai'; "
                "install them and restart the service"
            ),
            http_status=503,
        )

    runner = request.app.state.agent_runner
    semaphore: asyncio.Semaphore = request.app.state.agent_semaphore

    async def event_stream() -> AsyncIterator[str]:
        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=0.01)
        except TimeoutError:
            yield _sse(
                "error",
                {
                    "error": {
                        "code": "AGENT_OVERLOADED",
                        "stage": None,
                        "message": "too many concurrent agent runs, retry shortly",
                    }
                },
            )
            return
        try:
            iterator = runner.run(kb_id, body.query).__aiter__()
            while True:
                try:
                    event: AgentEvent = await asyncio.wait_for(
                        iterator.__anext__(), timeout=_HEARTBEAT_SECONDS
                    )
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                except StopAsyncIteration:
                    break
                except AppError as exc:
                    yield _sse(
                        "error",
                        {"error": {"code": exc.code, "stage": exc.stage, "message": exc.message}},
                    )
                    break
                yield _sse(event.event, event.data)
        finally:
            semaphore.release()

    return StreamingResponse(
        event_stream(), media_type="text/event-stream", headers=_SSE_HEADERS
    )
