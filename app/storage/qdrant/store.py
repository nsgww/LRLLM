"""Qdrant VectorStore 的实现（06-检索规范第 4/10 节，
09-数据库模式第 10 节）。

- 点 ID 即 chunk_id，从而支持精确删除和数据同步。
- 所有作用域/元数据过滤器都会推入 Qdrant 查询过滤器中，
  在数据被调取后绝不会在内存中应用。
"""

from qdrant_client import AsyncQdrantClient
from qdrant_client import models as qm

from app.core.errors import AppError, QueryStage
from app.domain.retrieval import MetadataFilter, RetrievalHit, RetrievalSource
from app.storage.base import VectorPoint

PAYLOAD_INDEX_FIELDS = (
    "knowledge_base_id",
    "document_id",
    "product",
    "version",
    "chunk_type",
)


class QdrantVectorStore:
    def __init__(self, url: str, collection: str, dimension: int) -> None:
        self._client = AsyncQdrantClient(url=url)
        self._collection = collection
        self._dimension = dimension

    async def ensure_collection(self) -> None:
        if not await self._client.collection_exists(self._collection):
            await self._client.create_collection(
                collection_name=self._collection,
                vectors_config=qm.VectorParams(
                    size=self._dimension,
                    distance=qm.Distance.COSINE,
                ),
            )
        for field in PAYLOAD_INDEX_FIELDS:
            await self._client.create_payload_index(
                collection_name=self._collection,
                field_name=field,
                field_schema=qm.PayloadSchemaType.KEYWORD,
            )

    async def validate_dimension(self) -> None:
        """Startup check: collection vector size must equal the configured
        embedding dimension, otherwise refuse to run (10 section 8)."""
        info = await self._client.get_collection(self._collection)
        actual = info.config.params.vectors.size
        if actual != self._dimension:
            raise AppError(
                code="EMBEDDING_DIMENSION_MISMATCH",
                message=(
                    f"qdrant collection '{self._collection}' dimension {actual} "
                    f"!= configured embedding dimension {self._dimension}"
                ),
                stage=QueryStage.VECTOR_RETRIEVAL,
            )

    @staticmethod
    def _build_filter(filters: MetadataFilter) -> qm.Filter:
        must = [
            qm.FieldCondition(
                key="knowledge_base_id",
                match=qm.MatchValue(value=filters.knowledge_base_id),
            )
        ]
        if filters.product is not None:
            must.append(
                qm.FieldCondition(key="product", match=qm.MatchValue(value=filters.product))
            )
        if filters.version is not None:
            must.append(
                qm.FieldCondition(key="version", match=qm.MatchValue(value=filters.version))
            )
        if filters.doc_class is not None:
            must.append(
                qm.FieldCondition(key="doc_class", match=qm.MatchValue(value=filters.doc_class))
            )
        return qm.Filter(must=must)

    async def upsert(self, points: list[VectorPoint]) -> None:
        await self._client.upsert(
            collection_name=self._collection,
            points=[
                qm.PointStruct(id=p.chunk_id, vector=p.vector, payload=p.payload)
                for p in points
            ],
        )

    async def delete(self, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        await self._client.delete(
            collection_name=self._collection,
            points_selector=qm.PointIdsList(points=chunk_ids),
        )

    async def search(
        self,
        vector: list[float],
        filters: MetadataFilter,
        top_k: int,
    ) -> list[RetrievalHit]:
        if len(vector) != self._dimension:
            raise AppError(
                code="EMBEDDING_DIMENSION_MISMATCH",
                message=f"query vector dimension {len(vector)} != {self._dimension}",
                stage=QueryStage.VECTOR_RETRIEVAL,
            )
        results = await self._client.search(
            collection_name=self._collection,
            query_vector=vector,
            query_filter=self._build_filter(filters),
            limit=top_k,
            with_payload=True,
        )
        return [
            RetrievalHit(
                chunk_id=str(r.id),
                document_id=str((r.payload or {}).get("document_id", "")),
                score=r.score,
                source=RetrievalSource.VECTOR,
                payload=dict(r.payload or {}),
            )
            for r in results
        ]
