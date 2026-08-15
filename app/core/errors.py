"""Error classification (single source of truth).

Query stages follow 02-query-rag-spec section 21.
Ingestion codes follow 04-ingestion-pipeline-spec section 32.
Never collapse failures into a generic RAG_ERROR.
"""

from enum import Enum


class QueryStage(str, Enum):
    QUERY_UNDERSTANDING = "QUERY_UNDERSTANDING"
    QUERY_REWRITE = "QUERY_REWRITE"
    QUERY_DECOMPOSITION = "QUERY_DECOMPOSITION"
    RETRIEVAL_PLANNING = "RETRIEVAL_PLANNING"
    METADATA_FILTER = "METADATA_FILTER"
    VECTOR_RETRIEVAL = "VECTOR_RETRIEVAL"
    KEYWORD_RETRIEVAL = "KEYWORD_RETRIEVAL"
    RERANKING = "RERANKING"
    EVIDENCE_CHECK = "EVIDENCE_CHECK"
    CONTEXT_BUILDING = "CONTEXT_BUILDING"
    LLM_GENERATION = "LLM_GENERATION"


class IngestionErrorCode(str, Enum):
    FILE_INVALID = "FILE_INVALID"
    FILE_UNSUPPORTED = "FILE_UNSUPPORTED"
    FILE_EMPTY = "FILE_EMPTY"
    PARSER_FAILED = "PARSER_FAILED"
    METADATA_INVALID = "METADATA_INVALID"
    METADATA_CONFLICT = "METADATA_CONFLICT"
    SECTION_PARSE_FAILED = "SECTION_PARSE_FAILED"
    CHUNK_FAILED = "CHUNK_FAILED"
    EMBEDDING_FAILED = "EMBEDDING_FAILED"
    VECTOR_INDEX_FAILED = "VECTOR_INDEX_FAILED"
    KEYWORD_INDEX_FAILED = "KEYWORD_INDEX_FAILED"
    DATABASE_FAILED = "DATABASE_FAILED"


class AppError(Exception):
    """Structured application error carried to API / Trace."""

    def __init__(
        self,
        code: str,
        message: str,
        stage: QueryStage | None = None,
        http_status: int = 500,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.stage = stage.value if stage else None
        self.http_status = http_status


class IngestionError(Exception):
    """Ingestion failure, always locatable to a concrete stage."""

    def __init__(self, code: IngestionErrorCode, message: str, stage: str) -> None:
        super().__init__(message)
        self.code = code.value
        self.message = message
        self.stage = stage
