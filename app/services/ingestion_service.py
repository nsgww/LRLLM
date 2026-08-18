"""Document upload / reindex / delete (05-api-spec section 6,
04-ingestion-pipeline-spec sections 3/24/25).

- Upload only creates Document + Job; parsing is async (worker).
- Duplicate content in the same knowledge base is rejected (409).
- Delete is soft delete: retrieval exclusion is immediate, Qdrant point
  removal happens here, physical row cleanup is left to background jobs.
"""

import hashlib
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError
from app.domain.document import Document
from app.domain.ingestion import IngestionJob
from app.storage.base import VectorStore
from app.storage.postgres.repositories import (
    ChunkRepository,
    DocumentRepository,
    IngestionJobRepository,
    KnowledgeBaseRepository,
)

_ALLOWED_SUFFIXES = (".md", ".markdown")


@dataclass
class UploadResult:
    document_id: str
    ingestion_job_id: str
    content_hash: str
    status: str


class IngestionService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        vector_store: VectorStore,
    ) -> None:
        self._session_factory = session_factory
        self._vector_store = vector_store

    async def upload(
        self,
        kb_id: str,
        filename: str,
        content: bytes,
        metadata: dict,
    ) -> UploadResult:
        if not filename.lower().endswith(_ALLOWED_SUFFIXES):
            raise AppError(
                code="FILE_UNSUPPORTED",
                message="v0.1 only supports Markdown (.md) upload",
                http_status=400,
            )
        if not content or not content.strip():
            raise AppError(code="FILE_EMPTY", message="empty file", http_status=400)

        content_hash = hashlib.sha256(content).hexdigest()

        async with self._session_factory() as session:
            kb = await KnowledgeBaseRepository(session).get(kb_id)
            if kb is None:
                raise AppError(
                    code="KNOWLEDGE_BASE_NOT_FOUND",
                    message=f"knowledge base {kb_id} not found",
                    http_status=404,
                )
            documents = DocumentRepository(session)
            existing = await documents.get_by_hash(kb_id, content_hash)
            if existing is not None:
                raise AppError(
                    code="DOCUMENT_ALREADY_EXISTS",
                    message=f"identical content already exists as document {existing.id}",
                    http_status=409,
                )

            title = metadata.get("title") or filename.rsplit(".", 1)[0]
            document = await documents.create(
                Document(
                    knowledge_base_id=kb_id,
                    title=title,
                    doc_class=metadata.get("doc_class"),
                    source=metadata.get("source"),
                    product=metadata.get("product"),
                    version=metadata.get("version"),
                    content=content.decode("utf-8"),
                    content_hash=content_hash,
                )
            )
            job = await IngestionJobRepository(session).create(
                IngestionJob(
                    knowledge_base_id=kb_id,
                    document_id=str(document.id),
                    content_hash=content_hash,
                )
            )
            await session.commit()
            return UploadResult(
                document_id=str(document.id),
                ingestion_job_id=str(job.id),
                content_hash=content_hash,
                status="PENDING",
            )

    async def reindex(self, document_id: str) -> UploadResult:
        async with self._session_factory() as session:
            documents = DocumentRepository(session)
            document = await documents.get(document_id)
            if document is None:
                raise AppError(
                    code="DOCUMENT_NOT_FOUND",
                    message=f"document {document_id} not found",
                    http_status=404,
                )
            job = await IngestionJobRepository(session).create(
                IngestionJob(
                    knowledge_base_id=str(document.knowledge_base_id),
                    document_id=document_id,
                    content_hash=document.content_hash,
                )
            )
            await session.commit()
            return UploadResult(
                document_id=document_id,
                ingestion_job_id=str(job.id),
                content_hash=document.content_hash,
                status="PENDING",
            )

    async def delete(self, document_id: str) -> None:
        async with self._session_factory() as session:
            documents = DocumentRepository(session)
            chunks = ChunkRepository(session)
            document = await documents.get(document_id)
            if document is None:
                raise AppError(
                    code="DOCUMENT_NOT_FOUND",
                    message=f"document {document_id} not found",
                    http_status=404,
                )
            chunk_ids = await chunks.list_ids_by_document(document_id)
            # soft delete first: retrieval exclusion is effective immediately
            await documents.soft_delete(document_id)
            await chunks.soft_delete_by_document(document_id)
            await session.commit()
        # remove vectors so the document disappears from vector recall too
        await self._vector_store.delete(chunk_ids)
