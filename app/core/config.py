"""中央配置（10-项目结构 第5节）。

所有环境驱动的设置均位于此处。检索参数应遵循
06-检索规范 第12节的规定，且必须保持可配置状态，绝不能硬编码。
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RAG_",
        env_file=".env",
        extra="ignore",
    )

    app_name: str = "private-knowledge-rag"
    api_prefix: str = "/v1"

    # infrastructure
    postgres_dsn: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/rag"
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "chunks_v1"
    redis_url: str = "redis://localhost:6379/0"

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

    # prompt loading
    prompt_cache_ttl_seconds: int = 5


def get_settings() -> Settings:
    return Settings()
