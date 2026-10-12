"""Ingestion job endpoints (05-api-spec section 7)."""

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import require_api_key, require_kb_id
from app.api.pagination import decode_cursor, next_cursor
from app.api.schemas import IngestionJobOut, Page
from app.domain.ingestion import JobStatus

router = APIRouter(tags=["ingestion-jobs"], dependencies=[Depends(require_api_key)])


def _job_out(row) -> IngestionJobOut:
    error = None
    if row.error_code:
        error = {"code": row.error_code, "message": row.error_message}
    return IngestionJobOut(
        job_id=str(row.id),
        document_id=str(row.document_id),
        status=row.status.value,
        stage=row.stage,
        section_count=row.section_count,
        chunk_count=row.chunk_count,
        error=error,
        created_at=row.created_at,
        finished_at=row.finished_at,
    )


@router.get("/ingestion-jobs/{job_id}", response_model=IngestionJobOut)
async def get_job(
    job_id: str,
    request: Request,
    kb_id: str = Depends(require_kb_id),
) -> IngestionJobOut:
    return _job_out(await request.app.state.ingestion_service.get_job(job_id, kb_id))


@router.get("/ingestion-jobs", response_model=Page[IngestionJobOut])
async def list_jobs(
    request: Request,
    document_id: str | None = None,
    status: JobStatus | None = None,
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = None,
    kb_id: str = Depends(require_kb_id),
) -> Page[IngestionJobOut]:
    rows, has_more = await request.app.state.ingestion_service.list_jobs(
        document_id, status, limit, decode_cursor(cursor) if cursor else None, kb_id
    )
    return Page[IngestionJobOut](
        items=[_job_out(r) for r in rows],
        next_cursor=next_cursor(rows, has_more),
        has_more=has_more,
    )
