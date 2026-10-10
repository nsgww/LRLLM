"""Document endpoints (05-api-spec section 6)."""

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile

from app.api.deps import require_api_key, require_kb_id
from app.api.pagination import decode_cursor, next_cursor
from app.api.schemas import DocumentOut, Page, UploadOut
from app.core.config import get_settings
from app.core.errors import AppError

router = APIRouter(tags=["documents"], dependencies=[Depends(require_api_key)])

# 分块读取大小：既保证内存占用可控，又避免过多小读
_READ_CHUNK = 1 << 20  # 1 MiB


async def _read_upload(file: UploadFile) -> bytes:
    """流式读取上传内容，超过上限立即中止（413）。

    直接 `await file.read()` 会把整个文件拉进内存——一个 2GB 的上传
    即可让进程 OOM。这里按块累计，超限即刻拒绝，不再继续读取。
    """
    limit = get_settings().max_upload_bytes
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_READ_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise AppError(
                code="FILE_TOO_LARGE",
                message=f"file exceeds the {limit} byte upload limit",
                http_status=413,
            )
        chunks.append(chunk)
    return b"".join(chunks)


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
    content = await _read_upload(file)
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


@router.get("/documents", response_model=Page[DocumentOut])
async def list_documents(
    request: Request,
    limit: int = 50,
    cursor: str | None = None,
    kb_id: str = Depends(require_kb_id),
) -> Page[DocumentOut]:
    rows, has_more = await request.app.state.ingestion_service.list_documents(
        kb_id, limit, decode_cursor(cursor) if cursor else None
    )
    return Page[DocumentOut](
        items=[_doc_out(r) for r in rows],
        next_cursor=next_cursor(rows, has_more),
        has_more=has_more,
    )


@router.get("/documents/{document_id}", response_model=DocumentOut)
async def get_document(document_id: str, request: Request) -> DocumentOut:
    return _doc_out(await request.app.state.ingestion_service.get_document(document_id))


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(document_id: str, request: Request) -> None:
    await request.app.state.ingestion_service.delete(document_id)


@router.post("/documents/{document_id}/reindex", response_model=UploadOut, status_code=202)
async def reindex_document(document_id: str, request: Request) -> UploadOut:
    return _upload_out(await request.app.state.ingestion_service.reindex(document_id))
