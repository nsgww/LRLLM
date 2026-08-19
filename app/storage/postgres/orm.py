"""ORM 行与 09-database-schema DDL 保持一致。

枚举类型复用域枚举；标签与 PostgreSQL 枚举类型一致。
search_tsv 由数据库触发器（09 节第 5 部分）维护，
应用程序代码绝不会写入该字段。
"""

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.domain.chunk import ChunkType
from app.domain.document import DocumentStatus
from app.domain.ingestion import JobStatus
from app.domain.retrieval import EvidenceStatus


class Base(DeclarativeBase):
    pass


class KnowledgeBaseRow(Base):
    __tablename__ = "knowledge_bases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class DocumentRow(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(sa.Text, nullable=False)
    doc_class: Mapped[str | None] = mapped_column(sa.Text)
    source: Mapped[str | None] = mapped_column(sa.Text)
    product: Mapped[str | None] = mapped_column(sa.Text)
    version: Mapped[str | None] = mapped_column(sa.Text)
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    parser_version: Mapped[str | None] = mapped_column(sa.Text)
    chunker_version: Mapped[str | None] = mapped_column(sa.Text)
    embedding_model: Mapped[str | None] = mapped_column(sa.Text)
    embedding_model_version: Mapped[str | None] = mapped_column(sa.Text)
    processing_fingerprint: Mapped[str | None] = mapped_column(sa.Text)
    status: Mapped[DocumentStatus] = mapped_column(
        sa.Enum(DocumentStatus, name="document_status", create_type=False),
        nullable=False,
        default=DocumentStatus.PENDING,
    )
    error_code: Mapped[str | None] = mapped_column(sa.Text)
    error_message: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class SectionRow(Base):
    __tablename__ = "sections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    parent_section_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("sections.id")
    )
    heading: Mapped[str] = mapped_column(sa.Text, nullable=False)
    heading_path: Mapped[str] = mapped_column(sa.Text, nullable=False)
    level: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    section_order: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    line_start: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    line_end: Mapped[int] = mapped_column(sa.Integer, nullable=False)


class ChunkRow(Base):
    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    section_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("sections.id")
    )
    text: Mapped[str] = mapped_column(sa.Text, nullable=False)
    raw_content: Mapped[str | None] = mapped_column(sa.Text)
    heading_path: Mapped[str] = mapped_column(sa.Text, nullable=False)
    line_start: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    line_end: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    chunk_type: Mapped[ChunkType] = mapped_column(
        sa.Enum(ChunkType, name="chunk_type", create_type=False),
        nullable=False,
        default=ChunkType.TEXT,
    )
    chunk_index: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    token_count: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    product: Mapped[str | None] = mapped_column(sa.Text)
    version: Mapped[str | None] = mapped_column(sa.Text)
    embedding_model: Mapped[str | None] = mapped_column(sa.Text)
    embedding_model_version: Mapped[str | None] = mapped_column(sa.Text)
    search_tsv: Mapped[str | None] = mapped_column(TSVECTOR)  # trigger-maintained
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class IngestionJobRow(Base):
    __tablename__ = "ingestion_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[JobStatus] = mapped_column(
        sa.Enum(JobStatus, name="job_status", create_type=False),
        nullable=False,
        default=JobStatus.PENDING,
    )
    stage: Mapped[str | None] = mapped_column(sa.Text)
    parser: Mapped[str | None] = mapped_column(sa.Text)
    parser_version: Mapped[str | None] = mapped_column(sa.Text)
    content_hash: Mapped[str | None] = mapped_column(sa.Text)
    section_count: Mapped[int | None] = mapped_column(sa.Integer)
    chunk_count: Mapped[int | None] = mapped_column(sa.Integer)
    embedding_count: Mapped[int | None] = mapped_column(sa.Integer)
    error_code: Mapped[str | None] = mapped_column(sa.Text)
    error_message: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class ConversationRow(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())


class ConversationMessageRow(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(
        sa.Enum("USER", "ASSISTANT", "SYSTEM", name="message_role", create_type=False),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    answer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())


class QueryTraceRow(Base):
    __tablename__ = "query_traces"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("conversations.id")
    )
    answer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    raw_query: Mapped[str] = mapped_column(sa.Text, nullable=False)
    rewritten_query: Mapped[str | None] = mapped_column(sa.Text)
    intent: Mapped[str | None] = mapped_column(sa.Text)
    product: Mapped[str | None] = mapped_column(sa.Text)
    version: Mapped[str | None] = mapped_column(sa.Text)
    sub_queries: Mapped[dict | None] = mapped_column(JSONB)
    retrieval_strategy: Mapped[str | None] = mapped_column(sa.Text)
    metadata_filters: Mapped[dict] = mapped_column(JSONB, nullable=False)
    vector_results: Mapped[dict | None] = mapped_column(JSONB)
    keyword_results: Mapped[dict | None] = mapped_column(JSONB)
    fused_candidates: Mapped[dict | None] = mapped_column(JSONB)
    reranked_results: Mapped[dict | None] = mapped_column(JSONB)
    reranker_fallback: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    evidence_status: Mapped[EvidenceStatus | None] = mapped_column(
        sa.Enum(EvidenceStatus, name="evidence_status", create_type=False)
    )
    evidence_results: Mapped[dict | None] = mapped_column(JSONB)
    selected_chunks: Mapped[dict | None] = mapped_column(JSONB)
    context_token_count: Mapped[int | None] = mapped_column(sa.Integer)
    final_answer: Mapped[str | None] = mapped_column(sa.Text)
    prompt_versions: Mapped[dict | None] = mapped_column(JSONB)
    error_stage: Mapped[str | None] = mapped_column(sa.Text)
    latency_ms: Mapped[int | None] = mapped_column(sa.Integer)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())


class PromptTemplateRow(Base):
    __tablename__ = "prompt_templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(sa.Text, nullable=False)
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    variables: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(
        sa.Enum("DRAFT", "PUBLISHED", "ARCHIVED", name="prompt_status", create_type=False),
        nullable=False,
        default="DRAFT",
    )
    created_by: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
