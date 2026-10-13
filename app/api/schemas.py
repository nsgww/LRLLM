"""Request / response schemas."""

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """Cursor pagination envelope (05-api-spec section 12)."""

    items: list[T]
    next_cursor: str | None = None
    has_more: bool = False


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


class AgentRequest(BaseModel):
    """Agent 请求体（/v1/agent）。

    ``conversation_id`` 可选：传入则接续该会话历史（必须属于当前 KB），
    否则隐式新建。Agent 的中间工具调用轨迹仍只在单次请求内闭环，
    但最终答案会写回会话，与 /v1/query 的多轮行为一致。
    """

    query: str
    conversation_id: str | None = None


class EvidenceItemOut(BaseModel):
    document_id: str
    document_title: str | None
    chunk_id: str
    source_type: str | None = None
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


class WikiPageOut(BaseModel):
    id: str
    slug: str
    title: str
    summary: str
    status: str
    revision_count: int
    updated_at: datetime | None = None


class WikiRevisionOut(BaseModel):
    version: int
    content: str
    change_note: str
    source_answer_id: str | None = None
    source_query: str = ""
    evidence: list = []
    created_at: datetime | None = None


class WikiPageDetailOut(BaseModel):
    id: str
    slug: str
    title: str
    summary: str
    status: str
    revision_count: int
    created_at: datetime | None = None
    updated_at: datetime | None = None
    revisions: list[WikiRevisionOut]


class WikiDistillOut(BaseModel):
    created: bool
    skipped: bool
    page_id: str | None = None
    revision_version: int | None = None
    slug: str = ""
    title: str = ""
    reason: str = ""
