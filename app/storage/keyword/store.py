"""PostgreSQL 关键字搜索（06-retrieval-spec 第 5 节）。

- 基于触发器维护的加权 tsvector 进行全文搜索（09 第 5 节）。
- pg_trgm 相似度是 CJK 文本以及 API 名称、错误代码和版本字符串等
  精确令牌的备用方案，因为 FTS 的“简单”配置
  无法对这些内容进行分段。
- 范围/元数据过滤器是 SQL WHERE 条件，绝不会在内存中处理。

upsert/delete 操作为空操作：块已存在于同一 PostgreSQL
数据库中（ChunkRepository 负责写入操作，触发器维护 search_tsv，
而软删除会立即将行从搜索结果中排除）。
"""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.retrieval import MetadataFilter, RetrievalHit, RetrievalSource

_FTS_SQL = """
SELECT c.id::text AS chunk_id,
       c.document_id::text AS document_id,
       ts_rank(c.search_tsv, q) AS score,
       c.product, c.version, c.chunk_type::text AS chunk_type,
       c.heading_path
FROM chunks c
JOIN documents d ON d.id = c.document_id AND d.deleted_at IS NULL,
     plainto_tsquery('simple', :query) q
WHERE c.deleted_at IS NULL
  AND c.knowledge_base_id = :kb_id
  AND (:product IS NULL OR c.product = :product)
  AND (:version IS NULL OR c.version = :version)
  AND (:doc_class IS NULL OR d.doc_class = :doc_class)
  AND q @@ c.search_tsv
ORDER BY score DESC
LIMIT :top_k
"""

_TRGM_SQL = """
SELECT c.id::text AS chunk_id,
       c.document_id::text AS document_id,
       similarity(c.text, :query) AS score,
       c.product, c.version, c.chunk_type::text AS chunk_type,
       c.heading_path
FROM chunks c
JOIN documents d ON d.id = c.document_id AND d.deleted_at IS NULL
WHERE c.deleted_at IS NULL
  AND c.knowledge_base_id = :kb_id
  AND (:product IS NULL OR c.product = :product)
  AND (:version IS NULL OR c.version = :version)
  AND (:doc_class IS NULL OR d.doc_class = :doc_class)
  AND (c.text % :query OR c.heading_path % :query)
ORDER BY score DESC
LIMIT :top_k
"""


class PostgresKeywordStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def upsert(self, chunks: list) -> None:
        # Chunks are written by ChunkRepository; the tsvector trigger keeps
        # the keyword index in sync. Nothing to do here.
        return None

    async def delete(self, chunk_ids: list[str]) -> None:
        # Soft delete happens in ChunkRepository; search filters deleted_at.
        return None

    async def search(
        self,
        query: str,
        filters: MetadataFilter,
        top_k: int,
    ) -> list[RetrievalHit]:
        params = {
            "query": query,
            "kb_id": filters.knowledge_base_id,
            "product": filters.product,
            "version": filters.version,
            "doc_class": filters.doc_class,
            "top_k": top_k,
        }
        async with self._session_factory() as session:
            rows = (await session.execute(sa.text(_FTS_SQL), params)).mappings().all()
            if not rows:
                rows = (await session.execute(sa.text(_TRGM_SQL), params)).mappings().all()
        return [
            RetrievalHit(
                chunk_id=r["chunk_id"],
                document_id=r["document_id"],
                score=float(r["score"]),
                source=RetrievalSource.KEYWORD,
                payload={
                    "knowledge_base_id": filters.knowledge_base_id,
                    "product": r["product"],
                    "version": r["version"],
                    "chunk_type": r["chunk_type"],
                    "heading_path": r["heading_path"],
                },
            )
            for r in rows
        ]
