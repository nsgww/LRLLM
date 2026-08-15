"""Storage interfaces (04-ingestion-pipeline-spec section 23,
06-retrieval-spec section 10).

Filters are exact-match only and must be pushed down to the storage layer.
In-memory scope filtering after recall is forbidden.
"""

from dataclasses import dataclass, field
from typing import Protocol

from app.domain.retrieval import MetadataFilter, RetrievalHit


@dataclass
class VectorPoint:
    chunk_id: str
    vector: list[float]
    payload: dict = field(default_factory=dict)


class VectorStore(Protocol):
    async def upsert(self, points: list[VectorPoint]) -> None:
        ...

    async def delete(self, chunk_ids: list[str]) -> None:
        ...

    async def search(
        self,
        vector: list[float],
        filters: MetadataFilter,
        top_k: int,
    ) -> list[RetrievalHit]:
        ...


class KeywordStore(Protocol):
    async def upsert(self, chunks: list) -> None:
        ...

    async def delete(self, chunk_ids: list[str]) -> None:
        ...

    async def search(
        self,
        query: str,
        filters: MetadataFilter,
        top_k: int,
    ) -> list[RetrievalHit]:
        ...
