"""PostgreSQL keyword search (06-retrieval-spec section 5).

- FTS over the trigger-maintained weighted tsvector (09 section 5).
- pg_trgm similarity is the fallback for CJK text and exact tokens such as
  API names, error codes and version strings, which FTS 'simple' config
  cannot segment.
- Scope/metadata filters are SQL WHERE conditions, never in-memory.

upsert/delete are no-ops: chunks already live in the same PostgreSQL
database (ChunkRepository owns writes, the trigger maintains search_tsv,
and soft delete excludes rows from search immediately).
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
