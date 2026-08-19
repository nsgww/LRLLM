"""存储接口（04-数据导入管道规范第23节，
06-数据检索规范第10节）。

过滤器仅支持精确匹配，且必须下推至存储层。
禁止在数据检索后进行内存范围过滤。
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
