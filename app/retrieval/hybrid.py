"""Hybrid retrieval and RRF fusion (06-retrieval-spec sections 4-6, 11).

- Vector and keyword recall run concurrently.
- Single-path failure degrades to the other path and is recorded;
  both failing fails the request with a classified stage.
- Fusion: Reciprocal Rank Fusion, dedup by chunk_id, union of both lists.
"""

import asyncio
from dataclasses import dataclass, field

from app.core.config import Settings
from app.core.errors import AppError, QueryStage
from app.domain.retrieval import MetadataFilter, RetrievalHit
from app.embedding.interface import EmbeddingModel
from app.retrieval.planner import RetrievalStrategy
from app.storage.base import KeywordStore, VectorStore


@dataclass
class HybridResult:
    vector_hits: list[RetrievalHit] = field(default_factory=list)
    keyword_hits: list[RetrievalHit] = field(default_factory=list)
    candidates: list[tuple[str, float]] = field(default_factory=list)  # (chunk_id, rrf_score)
    vector_degraded: bool = False
    keyword_degraded: bool = False


class HybridRetriever:
    def __init__(
        self,
        vector_store: VectorStore,
        keyword_store: KeywordStore,
        embedding: EmbeddingModel,
        settings: Settings,
    ) -> None:
        self._vector_store = vector_store
        self._keyword_store = keyword_store
        self._embedding = embedding
        self._settings = settings

    async def retrieve(
        self,
        query: str,
        filters: MetadataFilter,
        strategy: RetrievalStrategy,
    ) -> HybridResult:
        vector_hits, keyword_hits = await asyncio.gather(
            self._vector_recall(query, filters, strategy),
            self._keyword_recall(query, filters, strategy),
            return_exceptions=True,
        )

        result = HybridResult()
        if isinstance(vector_hits, Exception):
            result.vector_degraded = True
            vector_hits = []
        if isinstance(keyword_hits, Exception):
            result.keyword_degraded = True
            keyword_hits = []

        if result.vector_degraded and result.keyword_degraded:
            raise AppError(
                code="RETRIEVAL_UNAVAILABLE",
                message="both vector and keyword retrieval failed",
                stage=QueryStage.VECTOR_RETRIEVAL,
            )

        result.vector_hits = vector_hits
        result.keyword_hits = keyword_hits
        result.candidates = rrf_fuse(
            vector_hits,
            keyword_hits,
            rrf_k=self._settings.rrf_k,
            limit=self._settings.candidate_limit,
        )
        return result

    async def _vector_recall(
        self, query: str, filters: MetadataFilter, strategy: RetrievalStrategy
    ) -> list[RetrievalHit]:
        vector = await self._embedding.embed_query(query)
        return await self._vector_store.search(vector, filters, strategy.top_k_vector)

    async def _keyword_recall(
        self, query: str, filters: MetadataFilter, strategy: RetrievalStrategy
    ) -> list[RetrievalHit]:
        return await self._keyword_store.search(query, filters, strategy.top_k_keyword)


def rrf_fuse(
    vector_hits: list[RetrievalHit],
    keyword_hits: list[RetrievalHit],
    rrf_k: int,
    limit: int,
) -> list[tuple[str, float]]:
    """score(chunk) = sum(1 / (rrf_k + rank)) across both lists (06 section 6)."""
    scores: dict[str, float] = {}
    for hits in (vector_hits, keyword_hits):
        for rank, hit in enumerate(hits, start=1):
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (rrf_k + rank)
    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return ordered[:limit]
