"""入站事件接入（12-agent-platform-spec §2.1）：POST /v1/events。

KB 作用域来自 ``X-Knowledge-Base-ID`` 头；事件归一化后入 ``EventQueue``（Redis），
异步处理（触发对应 Job / Agent）由消费端负责（后续接入）。

诚实化语义：队列不可用或入队失败时返回 503（EVENT_QUEUE_UNAVAILABLE），
**绝不谎报已受理**——在消费端/持久化兜底接入之前，宁可拒收也不丢事件。
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, Request

from app.api.deps import require_api_key, require_kb_id
from app.api.schemas import EventIn
from app.core.errors import AppError

router = APIRouter(tags=["events"], dependencies=[Depends(require_api_key)])


@router.post("/events", status_code=202)
async def ingest_event(
    body: EventIn,
    request: Request,
    kb_id: str = Depends(require_kb_id),
) -> dict:
    await request.app.state.kb_service.get(kb_id)  # 404 when missing/deleted
    queue = getattr(request.app.state, "event_queue", None)
    if queue is None or not queue.usable:
        raise AppError(
            code="EVENT_QUEUE_UNAVAILABLE",
            message="event queue is unavailable; event not accepted",
            http_status=503,
        )
    event_id = f"evt_{uuid.uuid4().hex[:16]}"
    accepted = await queue.enqueue(
        json.dumps(
            {
                "event_id": event_id,
                "type": body.type,
                "kb_id": kb_id,
                "payload": body.payload,
            },
            ensure_ascii=False,
        )
    )
    if not accepted:
        raise AppError(
            code="EVENT_QUEUE_UNAVAILABLE",
            message="event queue rejected the event",
            http_status=503,
        )
    return {"event_id": event_id, "type": body.type, "status": "queued"}
