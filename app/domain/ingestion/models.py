"""Ingestion domain models (04-ingestion-pipeline-spec sections 3/7/8)."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class BlockType(str, Enum):
    DOCUMENT = "DOCUMENT"
    HEADING = "HEADING"
    PARAGRAPH = "PARAGRAPH"
    LIST = "LIST"
    LIST_ITEM = "LIST_ITEM"
    CODE_BLOCK = "CODE_BLOCK"
    TABLE = "TABLE"
    QUOTE = "QUOTE"
    IMAGE = "IMAGE"
    HTML = "HTML"


@dataclass
class ASTBlock:
    type: BlockType
    content: str
    line_start: int
    line_end: int
    level: int | None = None
    heading_path: list[str] = field(default_factory=list)
    children: list["ASTBlock"] = field(default_factory=list)


@dataclass
class DocumentAST:
    metadata: dict = field(default_factory=dict)
    title: str | None = None
    blocks: list[ASTBlock] = field(default_factory=list)


class JobStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass
class IngestionJob:
    knowledge_base_id: str
    document_id: str
    id: str | None = None
    status: JobStatus = JobStatus.PENDING
    stage: str | None = None
    parser: str | None = None
    parser_version: str | None = None
    content_hash: str | None = None
    section_count: int | None = None
    chunk_count: int | None = None
    embedding_count: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
