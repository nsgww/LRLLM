"""Conversation endpoints (05-api-spec section 10)."""

from fastapi import APIRouter, Request

from app.api.pagination import decode_cursor, next_cursor
from app.api.schemas import ConversationOut, MessageOut, Page

router = APIRouter(tags=["conversations"])


@router.get("/conversations/{conversation_id}", response_model=ConversationOut)
async def get_conversation(conversation_id: str, request: Request) -> ConversationOut:
    row = await request.app.state.conversation_service.get(conversation_id)
    return ConversationOut(
        id=str(row.id),
        knowledge_base_id=str(row.knowledge_base_id),
        created_at=row.created_at,
    )


@router.get("/conversations/{conversation_id}/messages", response_model=Page[MessageOut])
async def list_messages(
    conversation_id: str,
    request: Request,
    limit: int = 50,
    cursor: str | None = None,
) -> Page[MessageOut]:
    rows, has_more = await request.app.state.conversation_service.list_messages(
        conversation_id, limit, decode_cursor(cursor) if cursor else None
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
