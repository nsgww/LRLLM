"""中央配置（10-项目结构 第5节）。

所有环境驱动的设置均位于此处。检索参数应遵循
06-检索规范 第12节的规定，且必须保持可配置状态，绝不能硬编码。
"""

from __future__ import annotations

from urllib.parse import urlparse

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 私网 / 保留网段前缀：出站 base_url 不得指向这些地址（防 SSRF 与云元数据探测）
_BLOCKED_HOST_PREFIXES = (
    "169.254.",  # link-local / 云元数据 169.254.169.254
    "127.",      # loopback
    "0.",
    "10.",
    "192.168.",
)

# loopback 与私网段的精确匹配项
_BLOCKED_HOSTS = frozenset({"localhost", "::1", "[::1]", "0.0.0.0", "metadata.google.internal"})


def _is_private_host(host: str) -> bool:
    h = host.strip().lower()
    if h in _BLOCKED_HOSTS:
        return True
    if any(h.startswith(p) for p in _BLOCKED_HOST_PREFIXES):
        return True
    # 172.16.0.0/12
    if h.startswith("172."):
        parts = h.split(".")
        if len(parts) > 1 and parts[1].isdigit() and 16 <= int(parts[1]) <= 31:
            return True
    return False


def _validate_outbound_base_url(value: str | None) -> str | None:
    """出站 provider 地址必须显式配置、使用 http(s)、且不得指向私网。

    这是 SSRF 防线：配置被注入为内网地址时，服务不会带着 API Key 去访问。
    如需在内网部署自建推理服务，设置 RAG_ALLOW_PRIVATE_BASE_URL=true 显式放行。
    """
    if value is None or not value.strip():
        return value
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"base_url must use http/https, got scheme '{parsed.scheme}'")
    if not parsed.hostname:
        raise ValueError(f"base_url has no host: {value!r}")
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RAG_",
        env_file=".env",
        extra="ignore",
    )

    app_name: str = "private-knowledge-rag"
    api_prefix: str = "/v1"

    # 安全：可选 API Key。为空时关闭鉴权（保持单机开发体验），
    # 一旦设置则所有 /v1 写操作与查询都要求 Authorization: Bearer <key>。
    api_key: str = ""
    # 显式放行私网 base_url（内网自建推理服务场景）
    allow_private_base_url: bool = False
    # 上传单文件大小上限
    max_upload_bytes: int = 50 * 1024 * 1024
    # /v1/query 全局并发上限（保护 LLM 配额与连接池）
    query_max_concurrency: int = 8

    # infrastructure
    postgres_dsn: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/rag"
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "chunks_v1"
    redis_url: str = "redis://localhost:6379/0"

    # database connection pool
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: float = 30.0
    db_pool_recycle: int = 1800

    # provider HTTP timeouts (seconds)
    llm_timeout_seconds: float = 120.0
    embedding_timeout_seconds: float = 60.0
    reranker_timeout_seconds: float = 30.0

    # provider retry (transient network / 5xx / 429)
    provider_max_attempts: int = 3
    provider_retry_backoff_seconds: float = 1.0

    # llm
    llm_provider: str = "openai"
    llm_model: str = ""
    llm_api_key: str = ""
    llm_base_url: str | None = None

    # embedding
    embedding_provider: str = "openai"
    embedding_model: str = ""
    embedding_model_version: str = "v1"
    embedding_dimension: int = 1536
    embedding_api_key: str = ""
    embedding_base_url: str | None = None

    # reranker
    reranker_provider: str = "none"
    reranker_model: str = ""
    reranker_api_key: str = ""
    reranker_base_url: str | None = None

    # retrieval parameters (06-retrieval-spec section 12)
    top_k_vector: int = 50
    top_k_keyword: int = 50
    rrf_k: int = 60
    candidate_limit: int = 50
    rerank_top_n: int = 10
    per_version_cap: int = 5
    min_score: float | None = None
    max_sub_queries: int = 4

    # chunking / context
    max_chunk_tokens: int = 512
    context_token_budget: int = 6000
    # 父块预算：子块检索、父块提供完整上下文（04 节 17.1）
    parent_chunk_tokens: int = 1200
    # 命中子块后是否在 Context 中扩展为父块全文
    context_expand_to_parent: bool = True
    # 语义切分：超长段落按句子 Embedding 相似度低谷断点（04 节 15.1）
    # 默认关闭；开启后入库阶段会额外消耗 Embedding 调用
    semantic_split_enabled: bool = False
    semantic_split_threshold: float = 0.5

    # prompt loading
    prompt_cache_ttl_seconds: int = 5

    # agent（自主工具调用）：LLM 自行决定下一步做什么
    # 关闭时 /v1/agent 返回 503，既有 /v1/query 管道完全不受影响
    agent_enabled: bool = True
    # ReAct 循环最大步数：防止 LLM 反复调用工具不收敛
    agent_max_iterations: int = 8
    # 单次工具调用返回给 LLM 的最大片段数（控制上下文膨胀）
    agent_tool_top_k: int = 5
    # 单轮 Agent 请求的 wall-clock 上限（秒），超时以 error 事件收敛
    agent_timeout_seconds: float = 180.0

    # ingestion worker resilience
    ingestion_max_attempts: int = 3
    ingestion_retry_backoff_seconds: int = 30
    ingestion_stale_job_timeout_seconds: int = 300
    ingestion_poll_interval_seconds: float = 2.0
    # Redis 任务队列快速通道（03 节技术选型）；关闭后 Worker 纯 DB 轮询
    redis_queue_enabled: bool = True
    ingestion_worker_concurrency: int = 4

    # background physical cleanup
    cleanup_batch_size: int = 200

    @field_validator("llm_base_url", "embedding_base_url", "reranker_base_url")
    @classmethod
    def _check_base_url(cls, value: str | None) -> str | None:
        _validate_outbound_base_url(value)
        return value

    def outbound_host_issues(self) -> list[str]:
        """私网 base_url 检查。单独成方法是因为校验器读不到兄弟字段
        （allow_private_base_url），必须等 Settings 实例化完成后才能判断。"""
        if self.allow_private_base_url:
            return []
        issues: list[str] = []
        for name, url in (
            ("llm_base_url", self.llm_base_url),
            ("embedding_base_url", self.embedding_base_url),
            ("reranker_base_url", self.reranker_base_url),
        ):
            if not url:
                continue
            host = urlparse(url).hostname or ""
            if _is_private_host(host):
                issues.append(
                    f"{name}={url!r} points at private/reserved host '{host}'; "
                    "set RAG_ALLOW_PRIVATE_BASE_URL=true if this is intentional"
                )
        return issues


def get_settings() -> Settings:
    return Settings()
