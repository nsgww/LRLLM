"""Knowledge base endpoints (05-api-spec section 5)."""

from fastapi import APIRouter, Request

from app.api.schemas import KnowledgeBaseCreate, KnowledgeBaseOut

router = APIRouter(tags=["knowledge-bases"])


def _out(row) -> KnowledgeBaseOut:
    return KnowledgeBaseOut(
        id=str(row.id),
        name=row.name,
        description=row.description,
        created_at=row.created_at,
    )


@router.post("/knowledge-bases", response_model=KnowledgeBaseOut, status_code=201)
async def create_kb(body: KnowledgeBaseCreate, request: Request) -> KnowledgeBaseOut:
    row = await request.app.state.kb_service.create(body.name, body.description)
    return _out(row)


@router.get("/knowledge-bases", response_model=list[KnowledgeBaseOut])
async def list_kbs(request: Request, limit: int = 50) -> list[KnowledgeBaseOut]:
    rows = await request.app.state.kb_service.list(limit)
    return [_out(r) for r in rows]


@router.get("/knowledge-bases/{kb_id}", response_model=KnowledgeBaseOut)
async def get_kb(kb_id: str, request: Request) -> KnowledgeBaseOut:
    return _out(await request.app.state.kb_service.get(kb_id))


@router.delete("/knowledge-bases/{kb_id}", status_code=204)
async def delete_kb(kb_id: str, request: Request) -> None:
    await request.app.state.kb_service.soft_delete(kb_id)
