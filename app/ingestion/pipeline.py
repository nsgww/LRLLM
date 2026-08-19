"""数据摄取管道编排（第04节 2/3/24/34）。

处理阶段顺序：HASH -> PARSE -> METADATA -> SECTION -> CHUNK -> EMBEDDING
-> VECTOR_INDEX -> KEYWORD_INDEX -> READY。

- 幂等性：处理指纹未发生变化时，将跳过重新处理。
- 每次失败均可定位到带有分类代码的具体阶段。
- 只有在所有索引均成功后，文档才会进入“READY”状态。
"""

import hashlib
import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.errors import IngestionError, IngestionErrorCode
from app.domain.chunk import Chunk
from app.domain.document import DocumentStatus
from app.domain.ingestion import ASTBlock, BlockType, JobStatus
from app.domain.section import Section
from app.embedding.interface import EmbeddingModel
from app.ingestion.chunkers.semantic import SemanticChunk, SemanticChunker
from app.ingestion.metadata import resolve_metadata
from app.ingestion.parsers.base import Parser
from app.ingestion.parsers.markdown import MarkdownParser
from app.storage.base import VectorPoint, VectorStore
from app.storage.postgres.repositories import (
    ChunkRepository,
    DocumentRepository,
    IngestionJobRepository,
    SectionRepository,
)

logger = logging.getLogger(__name__)

_STAGE_ERROR_CODES = {
    "PARSE": IngestionErrorCode.PARSER_FAILED,
    "METADATA": IngestionErrorCode.METADATA_INVALID,
    "SECTION": IngestionErrorCode.SECTION_PARSE_FAILED,
    "CHUNK": IngestionErrorCode.CHUNK_FAILED,
    "EMBEDDING": IngestionErrorCode.EMBEDDING_FAILED,
    "VECTOR_INDEX": IngestionErrorCode.VECTOR_INDEX_FAILED,
    "KEYWORD_INDEX": IngestionErrorCode.KEYWORD_INDEX_FAILED,
    "DB": IngestionErrorCode.DATABASE_FAILED,
}


@dataclass
class IngestionResult:
    job_id: str
    document_id: str
    status: JobStatus
    section_count: int = 0
    chunk_count: int = 0
    embedding_count: int = 0
    skipped: bool = False


class IngestionPipeline:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        vector_store: VectorStore,
        embedding: EmbeddingModel,
        settings: Settings,
        parser: Parser | None = None,
        chunker: SemanticChunker | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._vector_store = vector_store
        self._embedding = embedding
        self._settings = settings
        self._parser = parser or MarkdownParser()
        self._chunker = chunker or SemanticChunker(max_tokens=settings.max_chunk_tokens)

    async def process(self, job_id: str) -> IngestionResult:
        stage = "DB"
        try:
            async with self._session_factory() as session:
                jobs = IngestionJobRepository(session)
                documents = DocumentRepository(session)

                job = await jobs.get(job_id)
                if job is None:
                    raise IngestionError(
                        IngestionErrorCode.DATABASE_FAILED, f"job {job_id} not found", "DB"
                    )
                document = await documents.get(str(job.document_id))
                if document is None:
                    raise IngestionError(
                        IngestionErrorCode.DATABASE_FAILED,
                        f"document {job.document_id} not found or deleted",
                        "DB",
                    )

                document_id = str(document.id)
                result = IngestionResult(job_id=job_id, document_id=document_id, status=JobStatus.RUNNING)

                fingerprint = _processing_fingerprint(
                    document.content_hash,
                    self._parser.version,
                    self._chunker.version,
                    self._embedding.model_version,
                )
                if (
                    document.status == DocumentStatus.READY
                    and document.processing_fingerprint == fingerprint
                ):
                    await jobs.update(job_id, JobStatus.SUCCEEDED, stage="HASH")
                    await session.commit()
                    result.status = JobStatus.SUCCEEDED
                    result.skipped = True
                    return result

                await jobs.update(job_id, JobStatus.RUNNING, stage="PARSE")
                await documents.update_status(document_id, DocumentStatus.PROCESSING)
                await session.commit()

                # PARSE
                stage = "PARSE"
                ast = await self._parser.parse(
                    document.content.encode("utf-8"),
                    metadata={
                        "title": document.title,
                        "doc_class": document.doc_class,
                        "source": document.source,
                        "product": document.product,
                        "version": document.version,
                    },
                )

                # METADATA
                stage = "METADATA"
                resolved = resolve_metadata(
                    explicit=ast.metadata.get("explicit", {}),
                    front_matter=ast.metadata.get("front_matter", {}),
                )
                title = resolved.title or ast.title or document.title
                await documents.update_metadata(
                    document_id,
                    title=title,
                    doc_class=resolved.doc_class,
                    source=resolved.source,
                    product=resolved.product,
                    version=resolved.version,
                )
                await documents.update_processing(
                    document_id,
                    parser_version=self._parser.version,
                    chunker_version=self._chunker.version,
                    embedding_model=self._embedding.model_name,
                    embedding_model_version=self._embedding.model_version,
                    processing_fingerprint=fingerprint,
                )

                # SECTION
                stage = "SECTION"
                sections_repo = SectionRepository(session)
                chunks_repo = ChunkRepository(session)
                sections = _build_sections(ast.blocks, document_id)
                await sections_repo.delete_by_document(document_id)
                section_ids = await sections_repo.bulk_create(sections)
                section_id_by_path = {
                    tuple(s.heading_path.split(" / ")): sid
                    for s, sid in zip(sections, section_ids, strict=True)
                }

                # CHUNK
                stage = "CHUNK"
                old_chunk_ids = await chunks_repo.delete_by_document(document_id)
                semantic_chunks = self._chunker.chunk(ast)
                chunks = [
                    _to_chunk(
                        sc,
                        index=index,
                        document_id=document_id,
                        knowledge_base_id=str(document.knowledge_base_id),
                        section_id=_find_section_id(sc.heading_path, section_id_by_path),
                        product=resolved.product,
                        version=resolved.version,
                        embedding_model=self._embedding.model_name,
                        embedding_model_version=self._embedding.model_version,
                    )
                    for index, sc in enumerate(semantic_chunks)
                ]
                chunk_ids = await chunks_repo.bulk_create(chunks)
                await session.commit()

                # EMBEDDING
                stage = "EMBEDDING"
                await jobs.update(job_id, JobStatus.RUNNING, stage=stage)
                await session.commit()
                vectors = await self._embedding.embed_documents(
                    [
                        _embedding_text(title, resolved.product, resolved.version, sc)
                        for sc in semantic_chunks
                    ]
                )

                # VECTOR_INDEX
                stage = "VECTOR_INDEX"
                await self._vector_store.delete(old_chunk_ids)
                await self._vector_store.upsert(
                    [
                        VectorPoint(
                            chunk_id=chunk_id,
                            vector=vector,
                            payload={
                                "knowledge_base_id": str(document.knowledge_base_id),
                                "document_id": document_id,
                                "section_id": chunk.section_id,
                                "chunk_id": chunk_id,
                                "product": resolved.product,
                                "version": resolved.version,
                                "chunk_type": chunk.chunk_type.value,
                            },
                        )
                        for chunk_id, chunk, vector in zip(chunk_ids, chunks, vectors, strict=True)
                    ]
                )

                # KEYWORD_INDEX: PostgreSQL FTS trigger maintains search_tsv
                # on chunk insert; no separate step required.

                await jobs.update(
                    job_id,
                    JobStatus.SUCCEEDED,
                    stage="DONE",
                    section_count=len(sections),
                    chunk_count=len(chunks),
                    embedding_count=len(vectors),
                )
                await documents.update_status(document_id, DocumentStatus.READY)
                await session.commit()

                result.status = JobStatus.SUCCEEDED
                result.section_count = len(sections)
                result.chunk_count = len(chunks)
                result.embedding_count = len(vectors)
                return result

        except IngestionError as exc:
            await self._fail(job_id, exc.code, exc.message, exc.stage)
            raise
        except Exception as exc:
            code = _STAGE_ERROR_CODES.get(stage, IngestionErrorCode.DATABASE_FAILED)
            await self._fail(job_id, code.value, str(exc), stage)
            raise IngestionError(code, str(exc), stage) from exc

    async def _fail(self, job_id: str, code: str, message: str, stage: str) -> None:
        logger.error("ingestion job %s failed at %s: %s %s", job_id, stage, code, message)
        async with self._session_factory() as session:
            jobs = IngestionJobRepository(session)
            documents = DocumentRepository(session)
            job = await jobs.get(job_id)
            if job is not None:
                await jobs.update(
                    job_id, JobStatus.FAILED, stage=stage, error_code=code, error_message=message
                )
                status = (
                    DocumentStatus.CONFLICT
                    if code == IngestionErrorCode.METADATA_CONFLICT.value
                    else DocumentStatus.FAILED
                )
                await documents.update_status(str(job.document_id), status, code, message)
            await session.commit()


def _processing_fingerprint(
    content_hash: str,
    parser_version: str,
    chunker_version: str,
    embedding_model_version: str,
) -> str:
    """04 section 5: content + parser + chunker + embedding model version."""
    raw = "|".join([content_hash, parser_version, chunker_version, embedding_model_version])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _build_sections(blocks: list[ASTBlock], document_id: str) -> list[Section]:
    """Each heading becomes a section; line range extends to the next
    heading of the same or higher level (04 section 13)."""
    headings = [b for b in blocks if b.type == BlockType.HEADING]
    sections: list[Section] = []
    for order, block in enumerate(headings):
        line_end = block.line_end
        for later in headings[order + 1 :]:
            if later.level is not None and block.level is not None and later.level <= block.level:
                line_end = later.line_start - 1
                break
        else:
            line_end = max((b.line_end for b in blocks), default=block.line_end)

        parent_path = block.heading_path[:-1]
        parent_id = None
        for s in reversed(sections):
            if s.heading_path.split(" / ") == parent_path:
                parent_id = s.id
                break

        sections.append(
            Section(
                document_id=document_id,
                heading=block.content,
                heading_path=" / ".join(block.heading_path),
                level=block.level or 1,
                section_order=order,
                line_start=block.line_start,
                line_end=line_end,
                parent_section_id=parent_id,
            )
        )
    return sections


def _find_section_id(heading_path: list[str], by_path: dict[tuple[str, ...], str]) -> str | None:
    """Deepest section whose path is a prefix of the chunk path."""
    for depth in range(len(heading_path), 0, -1):
        prefix = tuple(heading_path[:depth])
        if prefix in by_path:
            return by_path[prefix]
    return None


def _to_chunk(
    sc: SemanticChunk,
    *,
    index: int,
    document_id: str,
    knowledge_base_id: str,
    section_id: str | None,
    product: str | None,
    version: str | None,
    embedding_model: str,
    embedding_model_version: str,
) -> Chunk:
    return Chunk(
        document_id=document_id,
        section_id=section_id,
        knowledge_base_id=knowledge_base_id,
        text=sc.text,
        raw_content=sc.raw_content,
        heading_path=" / ".join(sc.heading_path),
        line_start=sc.line_start,
        line_end=sc.line_end,
        chunk_index=index,
        token_count=sc.token_count,
        content_hash=sc.content_hash,
        chunk_type=sc.chunk_type,
        product=product,
        version=version,
        embedding_model=embedding_model,
        embedding_model_version=embedding_model_version,
    )


def _embedding_text(
    title: str | None,
    product: str | None,
    version: str | None,
    sc: SemanticChunk,
) -> str:
    """04 section 19: title + product + version + heading path + content."""
    parts = [p for p in (title, product, version, " / ".join(sc.heading_path), sc.text) if p]
    return "\n".join(parts)
