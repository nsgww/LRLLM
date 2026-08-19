"""Request / response schemas."""

from datetime import datetime

from pydantic import BaseModel


class KnowledgeBaseCreate(BaseModel):
    name: str
    description: str | None = None


class KnowledgeBaseOut(BaseModel):
    id: str
    name: str
    description: str | None
    created_at: datetime | None


class DocumentOut(BaseModel):
    id: str
    knowledge_base_id: str
    title: str
    doc_class: str | None
    source: str | None
    product: str | None
    version: str | None
    content_hash: str
    status: str
    created_at: datetime | None


class UploadOut(BaseModel):
    document_id: str
    ingestion_job_id: str
    content_hash: str
    status: str


class IngestionJobOut(BaseModel):
    job_id: str
    document_id: str
    status: str
    stage: str | None
    section_count: int | None
    chunk_count: int | None
    error: dict | None
    created_at: datetime | None
    finished_at: datetime | None


class QueryRequest(BaseModel):
    query: str
    conversation_id: str | None = None


class EvidenceItemOut(BaseModel):
    document_id: str
    document_title: str | None
    chunk_id: str
    product: str | None
    version: str | None
    heading_path: str | None
    line_start: int | None
    line_end: int | None
    excerpt: str | None


class EvidenceOut(BaseModel):
    answer_id: str
    evidence: list[EvidenceItemOut]


class ConversationOut(BaseModel):
    id: str
    knowledge_base_id: str
    created_at: datetime | None


class MessageOut(BaseModel):
    role: str
    content: str
    answer_id: str | None
    created_at: datetime | None
