"""LLM Wiki endpoints (11-llm-wiki-spec section 6).

KB-scoped (X-Knowledge-Base-ID) + cursor pagination, mirroring documents.py.
"""

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import require_api_key, require_kb_id
from app.api.pagination import decode_cursor, next_cursor
from app.core.config import get_settings
from app.core.errors import AppError
from app.api.schemas import (
    Page,
    WikiDistillOut,
    WikiPageDetailOut,
    WikiPageOut,
    WikiRevisionOut,
)

async def _require_wiki_enabled() -> None:
    """11 §7：RAG_WIKI_ENABLED=false 时所有 wiki 端点返回 503。"""
    if not get_settings().wiki_enabled:
        raise AppError(
            code="WIKI_DISABLED",
            message="LLM Wiki is disabled (RAG_WIKI_ENABLED=false)",
            http_status=503,
        )


router = APIRouter(
    tags=["wiki"],
    dependencies=[Depends(require_api_key), Depends(_require_wiki_enabled)],
)


def _page_out(row) -> WikiPageOut:
    return WikiPageOut(
        id=str(row.id),
        slug=row.slug,
        title=row.title,
        summary=row.summary,
        status=row.status.value,
        revision_count=row.revision_count,
        updated_at=row.updated_at,
    )


@router.get("/wiki/pages", response_model=Page[WikiPageOut])
async def list_pages(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = None,
    kb_id: str = Depends(require_kb_id),
) -> Page[WikiPageOut]:
    rows, has_more = await request.app.state.wiki_service.list_pages(
        kb_id, limit, decode_cursor(cursor) if cursor else None
    )
    return Page[WikiPageOut](
        items=[_page_out(r) for r in rows],
        next_cursor=next_cursor(rows, has_more),
        has_more=has_more,
    )


@router.get("/wiki/pages/{page_id}", response_model=WikiPageDetailOut)
async def get_page(
    page_id: str,
    request: Request,
    kb_id: str = Depends(require_kb_id),
) -> WikiPageDetailOut:
    page, revisions = await request.app.state.wiki_service.get_page(page_id, kb_id)
    return WikiPageDetailOut(
        id=str(page.id),
        slug=page.slug,
        title=page.title,
        summary=page.summary,
        status=page.status.value,
        revision_count=page.revision_count,
        created_at=page.created_at,
        updated_at=page.updated_at,
        revisions=[
            WikiRevisionOut(
                version=r.version,
                content=r.content,
                change_note=r.change_note,
                source_answer_id=str(r.source_answer_id) if r.source_answer_id else None,
                source_query=r.source_query,
                evidence=list(r.evidence or []),
                created_at=r.created_at,
            )
            for r in revisions
        ],
    )


@router.post(
    "/wiki/answers/{answer_id}/distill",
    response_model=WikiDistillOut,
    status_code=202,
)
async def distill_answer(
    answer_id: str,
    request: Request,
    kb_id: str = Depends(require_kb_id),
) -> WikiDistillOut:
    result = await request.app.state.wiki_service.distill(answer_id, kb_id)
    return WikiDistillOut(
        created=result.created,
        skipped=result.skipped,
        page_id=result.page_id,
        revision_version=result.revision_version,
        slug=result.slug,
        title=result.title,
        reason=result.reason,
    )


@router.delete("/wiki/pages/{page_id}", status_code=204)
async def delete_page(
    page_id: str,
    request: Request,
    kb_id: str = Depends(require_kb_id),
) -> None:
    await request.app.state.wiki_service.delete_page(page_id, kb_id)
