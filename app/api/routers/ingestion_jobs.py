"""Ingestion job endpoints (05-api-spec section 7)."""

from fastapi import APIRouter, Request

from app.api.schemas import IngestionJobOut

router = APIRouter(tags=["ingestion-jobs"])


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
async def get_job(job_id: str, request: Request) -> IngestionJobOut:
    return _job_out(await request.app.state.ingestion_service.get_job(job_id))


@router.get("/ingestion-jobs", response_model=list[IngestionJobOut])
async def list_jobs(
    request: Request,
    document_id: str | None = None,
    limit: int = 50,
) -> list[IngestionJobOut]:
    rows = await request.app.state.ingestion_service.list_jobs(document_id, limit)
    return [_job_out(r) for r in rows]
