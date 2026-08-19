"""Conversation endpoints (05-api-spec section 10)."""

from fastapi import APIRouter, Request

from app.api.schemas import ConversationOut, MessageOut

router = APIRouter(tags=["conversations"])


@router.get("/conversations/{conversation_id}", response_model=ConversationOut)
async def get_conversation(conversation_id: str, request: Request) -> ConversationOut:
    row = await request.app.state.conversation_service.get(conversation_id)
    return ConversationOut(
        id=str(row.id),
        knowledge_base_id=str(row.knowledge_base_id),
        created_at=row.created_at,
    )


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
async def list_messages(
    conversation_id: str,
    request: Request,
    limit: int = 50,
) -> list[MessageOut]:
    rows = await request.app.state.conversation_service.messages(conversation_id, limit)
    return [
        MessageOut(
            role=r.role,
            content=r.content,
            answer_id=str(r.answer_id) if r.answer_id else None,
            created_at=r.created_at,
        )
        for r in rows
    ]
