"""Document endpoints (05-api-spec section 6)."""

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile

from app.api.deps import require_kb_id
from app.api.schemas import DocumentOut, UploadOut

router = APIRouter(tags=["documents"])


def _doc_out(row) -> DocumentOut:
    return DocumentOut(
        id=str(row.id),
        knowledge_base_id=str(row.knowledge_base_id),
        title=row.title,
        doc_class=row.doc_class,
        source=row.source,
        product=row.product,
        version=row.version,
        content_hash=row.content_hash,
        status=row.status.value,
        created_at=row.created_at,
    )


def _upload_out(result) -> UploadOut:
    return UploadOut(
        document_id=result.document_id,
        ingestion_job_id=result.ingestion_job_id,
        content_hash=result.content_hash,
        status=result.status,
    )


@router.post("/documents", response_model=UploadOut, status_code=202)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    doc_class: str | None = Form(default=None),
    product: str | None = Form(default=None),
    version: str | None = Form(default=None),
    source: str | None = Form(default=None),
    kb_id: str = Depends(require_kb_id),
) -> UploadOut:
    content = await file.read()
    metadata = {
        key: value
        for key, value in {
            "title": title,
            "doc_class": doc_class,
            "product": product,
            "version": version,
            "source": source,
        }.items()
        if value
    }
    result = await request.app.state.ingestion_service.upload(
        kb_id, file.filename or "untitled.md", content, metadata
    )
    return _upload_out(result)


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(
    request: Request,
    limit: int = 50,
    kb_id: str = Depends(require_kb_id),
) -> list[DocumentOut]:
    rows = await request.app.state.ingestion_service.list_documents(kb_id, limit)
    return [_doc_out(r) for r in rows]


@router.get("/documents/{document_id}", response_model=DocumentOut)
async def get_document(document_id: str, request: Request) -> DocumentOut:
    return _doc_out(await request.app.state.ingestion_service.get_document(document_id))


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(document_id: str, request: Request) -> None:
    await request.app.state.ingestion_service.delete(document_id)


@router.post("/documents/{document_id}/reindex", response_model=UploadOut, status_code=202)
async def reindex_document(document_id: str, request: Request) -> UploadOut:
    return _upload_out(await request.app.state.ingestion_service.reindex(document_id))
