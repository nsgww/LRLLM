"""Query endpoint with SSE streaming (05-api-spec section 8).

Event order: meta first, done/error last. Citations and chunk content
are never included in any event.
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
