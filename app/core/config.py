"""中央配置（10-项目结构 第5节）。

所有环境驱动的设置均位于此处。检索参数应遵循
06-检索规范 第12节的规定，且必须保持可配置状态，绝不能硬编码。
"""

from __future__ import annotations

import ipaddress
from functools import lru_cache
from urllib.parse import urlparse

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 非 IP 的主机名黑名单：loopback 与云元数据端点（IP 字面量由 ipaddress 规范化判断）
_BLOCKED_HOSTS = frozenset({"localhost", "metadata.google.internal", "metadata", "instance-data"})


def _parse_ip_literal(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Parse an IP literal, tolerating the decimal/hex/octal forms that a naive
    string-prefix check would miss (e.g. ``2130706433``, ``0x7f000001``,
    ``0177.0.0.1``). Returns None for ordinary hostnames."""
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    if host.isdigit():  # decimal integer IPv4
        try:
            return ipaddress.ip_address(int(host))
        except (ValueError, OverflowError):
            return None
    low = host.lower()
    if low.startswith("0x"):  # hexadecimal IPv4
        try:
            return ipaddress.ip_address(int(low, 16))
        except (ValueError, OverflowError):
            return None
    parts = host.split(".")  # octal dotted-quad, e.g. 0177.0.0.1
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        try:
            return ipaddress.ip_address(".".join(str(int(p, 8)) for p in parts))
        except ValueError:
            return None
    # inet_aton short forms: "127.1" == 127.0.0.1, "10.1" == 10.0.0.1,
    # "192.168.1" == 192.168.0.1 (trailing octet fills the last position).
    if 2 <= len(parts) <= 3 and all(p.isdigit() for p in parts):
        nums = [int(p) for p in parts]
        if all(0 <= x <= 255 for x in nums):
            octets = nums[:-1] + [0] * (3 - (len(nums) - 1)) + [nums[-1]]
            try:
                return ipaddress.ip_address(".".join(map(str, octets)))
            except ValueError:
                return None
    return None


def _is_private_host(host: str) -> bool:
    h = host.strip().lower().rstrip(".")  # tolerate a trailing FQDN dot
    if h in _BLOCKED_HOSTS:
        return True
    ip = _parse_ip_literal(h)
    if ip is None:
        return False
    # unwrap IPv4-mapped IPv6 (e.g. ::ffff:127.0.0.1) before the range checks
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


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

    # policy engine（12-agent-platform-spec §2.4）：高风险工具动作处置
    policy_high_risk_requires_approval: bool = True  # 非 admin 高风险动作默认需审批
    policy_default_deny_high_risk: bool = False      # 不要求审批时是否默认拒绝高风险

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
    # 编排引擎：False=手写 ReAct(runner._loop，默认，零回归)；True=LangGraph 图(graph.py)
    agent_use_graph: bool = False
    # 身份头信任开关（12 §2.4）：X-Subject-* 头默认不被信任（客户端可伪造 admin），
    # 一律视为 api-client/user；仅在可信网关负责鉴权并覆写身份头时开启。
    trust_subject_headers: bool = False

    # llm wiki（11-llm-wiki-spec section 7）：把查询沉淀的知识持续整理成版本化页面
    wiki_enabled: bool = True            # 关闭时 wiki 端点 503、自动沉淀停；不影响 /v1/query
    wiki_in_retrieval: bool = True       # 混合检索是否并入 wiki 检索块（影子 document）
    wiki_max_content_tokens: int = 1200  # 单页面正文 token 上限（超出走 token_split 兜底）
    wiki_auto_min_evidence: int = 1      # 自动沉淀所需的最少证据条数（0 表示不要求）

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


@lru_cache
def get_settings() -> Settings:
    """Process-wide cached Settings.

    Repositories/routers hit this on hot paths (the auth dependency, the upload
    size limit, the agent endpoint). Re-reading and re-validating the ``.env``
    file on every request is pure overhead, so the parsed Settings are cached
    for the process lifetime. Tests construct ``Settings(...)`` directly and do
    not depend on this cache.
    """
    return Settings()
