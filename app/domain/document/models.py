"""Document domain model (aligned with 09-database-schema documents table)."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class DocumentStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"
    CONFLICT = "CONFLICT"


@dataclass
class Document:
    knowledge_base_id: str
    title: str
    content: str
    content_hash: str
    id: str | None = None
    doc_class: str | None = None
    source: str | None = None
    product: str | None = None
    version: str | None = None
    parser_version: str | None = None
    chunker_version: str | None = None
    embedding_model: str | None = None
    embedding_model_version: str | None = None
    processing_fingerprint: str | None = None
    status: DocumentStatus = DocumentStatus.PENDING
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    deleted_at: datetime | None = None
