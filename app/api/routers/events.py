"""入站事件接入（12-agent-platform-spec §2.1）：POST /v1/events。

KB 作用域来自 ``X-Knowledge-Base-ID`` 头；事件归一化后入 ``EventQueue``（Redis），
异步处理（触发对应 Job / Agent）由消费端负责（后续接入）。入队尽力而为：
即使队列不可用，事件已被接收即返回 202（消费端可另有兜底）。
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, Request

from app.api.deps import require_api_key, require_kb_id
from app.api.schemas import EventIn

router = APIRouter(tags=["events"], dependencies=[Depends(require_api_key)])


@router.post("/events", status_code=202)
async def ingest_event(
    body: EventIn,
    request: Request,
    kb_id: str = Depends(require_kb_id),
) -> dict:
    await request.app.state.kb_service.get(kb_id)  # 404 when missing/deleted
    event_id = f"evt_{uuid.uuid4().hex[:16]}"
    queue = getattr(request.app.state, "event_queue", None)
    if queue is not None:
        await queue.enqueue(
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
    return {"event_id": event_id, "type": body.type, "status": "queued"}
