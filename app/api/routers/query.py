"""使用 SSE 流式传输的查询端点（05-api-spec 第 8 节）。

事件顺序：元数据在前，完成/错误在后。引用和片段内容
绝不会包含在任何事件中。
"""

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.api.deps import require_kb_id
from app.api.schemas import QueryRequest

router = APIRouter(tags=["query"])


@router.post("/query")
async def query(
    body: QueryRequest,
    request: Request,
    kb_id: str = Depends(require_kb_id),
) -> StreamingResponse:
    await request.app.state.kb_service.get(kb_id)  # 404 when missing/deleted
    service = request.app.state.query_service

    async def event_stream() -> AsyncIterator[str]:
        async for event in service.ask(kb_id, body.query, body.conversation_id):
            yield (
                f"event: {event.event}\n"
                f"data: {json.dumps(event.data, ensure_ascii=False)}\n\n"
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
