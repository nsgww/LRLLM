"""错误分类（单一数据源）。

查询阶段遵循 02-query-rag-spec 第 21 节的规定。
数据摄取代码遵循 04-ingestion-pipeline-spec 第 32 节的规定。
切勿将各种故障归类为通用的 RAG_ERROR。
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


class PlatformErrorCode(str, Enum):
    """Agent 平台层错误码（12-agent-platform-spec §4，单一事实源）。

    - POLICY_DENIED：策略拒绝（API 层 403；工具层以 POLICY_DENIED: 文本反馈 LLM）。
    - APPROVAL_REQUIRED：高风险动作需审批（工具层文本反馈；审批闭环接入后 202/409）。
    - EVENT_QUEUE_UNAVAILABLE：事件队列不可用（/v1/events 返回 503，不谎报 queued）。
    - WIKI_CONFLICT：并发 distill 冲突（409，客户端可重试）。
    """

    POLICY_DENIED = "POLICY_DENIED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    EVENT_QUEUE_UNAVAILABLE = "EVENT_QUEUE_UNAVAILABLE"
    WIKI_CONFLICT = "WIKI_CONFLICT"


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
