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

    async def delete_by_knowledge_base(self, knowledge_base_id: str) -> None:
        """按 payload 过滤删除整个知识库的向量（05 节 5：KB 删除时必须调用）。

        不能用 `delete(list_ids_by_kb())` 代替——那需要把几万条 chunk id
        拉进内存；Qdrant 原生支持按 payload filter 服务端删除。
        """
        ...

    async def list_point_ids(self, batch: int = 1000) -> list[str]:
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
