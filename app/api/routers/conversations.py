"""Conversation endpoints (05-api-spec section 10)."""

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import require_api_key, require_kb_id
from app.api.pagination import decode_cursor, next_cursor
from app.api.schemas import ConversationOut, MessageOut, Page

router = APIRouter(tags=["conversations"], dependencies=[Depends(require_api_key)])


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    kb_id: str = Depends(require_kb_id),
) -> list[ConversationOut]:
    rows = await request.app.state.conversation_service.list_by_kb(kb_id, limit)
    return [
        ConversationOut(
            id=str(row.id),
            knowledge_base_id=str(row.knowledge_base_id),
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.post("/conversations", response_model=ConversationOut, status_code=201)
async def create_conversation(
    request: Request,
    kb_id: str = Depends(require_kb_id),
) -> ConversationOut:
    await request.app.state.kb_service.get(kb_id)  # 404 when missing/deleted
    row = await request.app.state.conversation_service.create(kb_id)
    return ConversationOut(
        id=str(row.id),
        knowledge_base_id=str(row.knowledge_base_id),
        created_at=row.created_at,
    )


@router.get("/conversations/{conversation_id}", response_model=ConversationOut)
async def get_conversation(
    conversation_id: str,
    request: Request,
    kb_id: str = Depends(require_kb_id),
) -> ConversationOut:
    row = await request.app.state.conversation_service.get(conversation_id, kb_id)
    return ConversationOut(
        id=str(row.id),
        knowledge_base_id=str(row.knowledge_base_id),
        created_at=row.created_at,
    )


@router.get("/conversations/{conversation_id}/messages", response_model=Page[MessageOut])
async def list_messages(
    conversation_id: str,
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = None,
    kb_id: str = Depends(require_kb_id),
) -> Page[MessageOut]:
    rows, has_more = await request.app.state.conversation_service.list_messages(
        conversation_id, limit, decode_cursor(cursor) if cursor else None, kb_id
    )
    return Page[MessageOut](
        items=[
            MessageOut(
                role=r.role,
                content=r.content,
                answer_id=str(r.answer_id) if r.answer_id else None,
                created_at=r.created_at,
            )
            for r in rows
        ],
        next_cursor=next_cursor(rows, has_more),
        has_more=has_more,
    )
