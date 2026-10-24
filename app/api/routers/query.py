"""使用 SSE 流式传输的查询端点（05-api-spec 第 8 节）。

事件顺序：元数据在前，完成/错误在后。引用和片段内容
绝不会包含在任何事件中。

并发保护：单次查询最坏触发 ~7 次外部调用（embedding / 检索 / rerank /
evidence LLM / 生成 LLM），因此由进程内信号量限制同时进行的查询数，
避免 LLM 配额与连接池被打爆。
"""

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.api.deps import require_api_key, require_kb_id
from app.api.schemas import QueryRequest
from app.core.errors import AppError

router = APIRouter(tags=["query"], dependencies=[Depends(require_api_key)])

# SSE 注释心跳：反代/网关常在 60s 无数据时断连，而首 token 可能更慢
_HEARTBEAT_SECONDS = 15.0
_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/query")
async def query(
    body: QueryRequest,
    request: Request,
    kb_id: str = Depends(require_kb_id),
) -> StreamingResponse:
    await request.app.state.kb_service.get(kb_id)  # 404 when missing/deleted
    service = request.app.state.query_service
    semaphore: asyncio.Semaphore = request.app.state.query_semaphore

    async def event_stream() -> AsyncIterator[str]:
        # 非阻塞抢占：满载时立刻回 429，不排队占住连接
        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=0.01)
        except TimeoutError:
            yield _sse(
                "error",
                {
                    "error": {
                        "code": "QUERY_OVERLOADED",
                        "stage": None,
                        "message": "too many concurrent queries, retry shortly",
                    }
                },
            )
            return
        # The in-flight __anext__ must survive heartbeat timeouts. Wrapping it in
        # a task and awaiting via asyncio.shield means a wait_for timeout cancels
        # only the shield wrapper, never the underlying step (a cancelled
        # __anext__ closes the async generator and silently truncates the stream).
        iterator = service.ask(kb_id, body.query, body.conversation_id).__aiter__()
        pending: asyncio.Task | None = None
        try:
            while True:
                if pending is None:
                    pending = asyncio.ensure_future(iterator.__anext__())
                try:
                    event = await asyncio.wait_for(
                        asyncio.shield(pending), timeout=_HEARTBEAT_SECONDS
                    )
                except TimeoutError:
                    yield ": keep-alive\n\n"  # SSE 注释帧，客户端忽略
                    continue
                except StopAsyncIteration:
                    break
                except AppError as exc:
                    yield _sse(
                        "error",
                        {"error": {"code": exc.code, "stage": exc.stage, "message": exc.message}},
                    )
                    break
                except Exception:  # noqa: BLE001 - SSE 必须收尾，不能静默断流
                    # 兜底：任何未分类异常都要以一个 error 帧收尾，
                    # 绝不在没有 done/error 事件的情况下静默断流。
                    yield _sse(
                        "error",
                        {
                            "error": {
                                "code": "INTERNAL_ERROR",
                                "stage": None,
                                "message": "internal error while streaming",
                            }
                        },
                    )
                    break
                pending = None
                yield _sse(event.event, event.data)
        finally:
            if pending is not None and not pending.done():
                pending.cancel()
            semaphore.release()

    return StreamingResponse(
        event_stream(), media_type="text/event-stream", headers=_SSE_HEADERS
    )
