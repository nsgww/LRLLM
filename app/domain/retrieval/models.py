"""Retrieval domain models (06-retrieval-spec sections 3/10, 02 section 12)."""

from dataclasses import dataclass, field
from enum import Enum


class RetrievalSource(str, Enum):
    VECTOR = "vector"
    KEYWORD = "keyword"


class EvidenceStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    INSUFFICIENT = "INSUFFICIENT"
    CONTRADICTED = "CONTRADICTED"


@dataclass(frozen=True)
class MetadataFilter:
    """Exact-match only filter. knowledge_base_id is mandatory and comes
    from the API scope contract, never from LLM output."""

    knowledge_base_id: str
    product: str | None = None
    version: str | None = None
    doc_class: str | None = None


@dataclass
class RetrievalHit:
    chunk_id: str
    document_id: str
    score: float
    source: RetrievalSource
    payload: dict = field(default_factory=dict)


@dataclass
class RankedChunk:
    """A chunk after fusion + rerank, ready for evidence check / context."""

    chunk_id: str
    document_id: str
    text: str
    score: float
    heading_path: str
    line_start: int
    line_end: int
    chunk_type: str = "TEXT"
    raw_content: str | None = None
    product: str | None = None
    version: str | None = None
    sub_query_id: str | None = None


@dataclass
class EvidenceResult:
    status: EvidenceStatus
    reason: str = ""
    supporting_chunk_ids: list[str] = field(default_factory=list)
