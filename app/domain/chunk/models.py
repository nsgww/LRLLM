"""Chunk domain model (04-ingestion-pipeline-spec section 18).

A chunk always knows its parent document and parent section.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class ChunkType(str, Enum):
    TEXT = "TEXT"
    CODE = "CODE"
    TABLE = "TABLE"
    LIST = "LIST"


@dataclass
class Chunk:
    document_id: str
    section_id: str | None
    knowledge_base_id: str
    text: str
    heading_path: str
    line_start: int
    line_end: int
    chunk_index: int
    token_count: int
    content_hash: str
    chunk_type: ChunkType = ChunkType.TEXT
    raw_content: str | None = None
    product: str | None = None
    version: str | None = None
    embedding_model: str | None = None
    embedding_model_version: str | None = None
    id: str | None = None
    created_at: datetime | None = None
    deleted_at: datetime | None = None
