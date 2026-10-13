"""Qdrant VectorStore 的实现（06-检索规范第 4/10 节，
09-数据库模式第 10 节）。

- 点 ID 即 chunk_id，从而支持精确删除和数据同步。
- 所有作用域/元数据过滤器都会推入 Qdrant 查询过滤器中，
  在数据被调取后绝不会在内存中应用。
"""

import logging

from qdrant_client import AsyncQdrantClient
from qdrant_client import models as qm

from app.core.errors import AppError, QueryStage
from app.domain.retrieval import MetadataFilter, RetrievalHit, RetrievalSource
from app.storage.base import VectorPoint

logger = logging.getLogger(__name__)

PAYLOAD_INDEX_FIELDS = (
    "knowledge_base_id",
    "document_id",
    "product",
    "version",
    "doc_class",
    "chunk_type",
    "source_type",
)


class QdrantVectorStore:
    def __init__(self, url: str, collection: str, dimension: int) -> None:
        self._client = AsyncQdrantClient(url=url)
        self._collection = collection
        self._dimension = dimension

    async def aclose(self) -> None:
        await self._client.close()

    async def health(self) -> None:
        """Raise if Qdrant is unreachable (used by /health)."""
        await self._client.get_collections()

    async def ensure_collection(self) -> None:
        if not await self._client.collection_exists(self._collection):
            await self._client.create_collection(
                collection_name=self._collection,
                vectors_config=qm.VectorParams(
                    size=self._dimension,
                    distance=qm.Distance.COSINE,
                ),
            )
        # Payload indexes are idempotent server-side, but re-issuing them on
        # every boot is wasted round trips; only create the missing ones.
        existing = await self._existing_payload_indexes()
        for field in PAYLOAD_INDEX_FIELDS:
            if field in existing:
                continue
            await self._client.create_payload_index(
                collection_name=self._collection,
                field_name=field,
                field_schema=qm.PayloadSchemaType.KEYWORD,
            )

    async def _existing_payload_indexes(self) -> set[str]:
        try:
            info = await self._client.get_collection(self._collection)
            schema = getattr(info, "payload_schema", None) or {}
            return set(schema.keys())
        except Exception:
            logger.warning("could not read payload schema; recreating indexes", exc_info=True)
            return set()

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
        # LLM Wiki（11 节 5）：关闭 wiki 入库检索时，排除 source_type='wiki' 的
        # 影子 document 向量块；默认并入。
        must_not = []
        if not filters.include_wiki:
            must_not.append(
                qm.FieldCondition(key="source_type", match=qm.MatchValue(value="wiki"))
            )
        return qm.Filter(must=must, must_not=must_not)

    async def upsert(self, points: list[VectorPoint]) -> None:
        # wait=True: the pipeline marks the document READY only after upsert
        # returns. Without it the write is async, so a READY document can be
        # queried before its vectors are visible, and an indexing failure is
        # never surfaced (qdrant-client defaults wait=False).
        await self._client.upsert(
            collection_name=self._collection,
            points=[
                qm.PointStruct(id=p.chunk_id, vector=p.vector, payload=p.payload)
                for p in points
            ],
            wait=True,
        )

    async def delete(self, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        # wait=True: cleanup relies on the point being gone before the PG row is
        # hard-deleted; an async delete would let a crash leave an orphan point.
        await self._client.delete(
            collection_name=self._collection,
            points_selector=qm.PointIdsList(points=chunk_ids),
            wait=True,
        )

    async def delete_by_knowledge_base(self, knowledge_base_id: str) -> None:
        """服务端按 payload 过滤删除整个知识库的向量（05 节 5）。

        传 chunk_id 列表会把整个知识库的 id 拉进内存；filter selector
        由 Qdrant 在服务端匹配，O(1) 网络流量。
        """
        await self._client.delete(
            collection_name=self._collection,
            points_selector=qm.FilterSelector(
                filter=qm.Filter(
                    must=[
                        qm.FieldCondition(
                            key="knowledge_base_id",
                            match=qm.MatchValue(value=knowledge_base_id),
                        )
                    ]
                )
            ),
            wait=True,
        )

    async def list_point_ids(self, batch: int = 1000) -> list[str]:
        """All point ids, for orphan reconciliation against PostgreSQL chunks."""
        ids: list[str] = []
        offset = None
        while True:
            points, offset = await self._client.scroll(
                collection_name=self._collection,
                limit=batch,
                offset=offset,
                with_payload=False,
                with_vectors=False,
            )
            ids.extend(str(p.id) for p in points)
            if offset is None:
                break
        return ids

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
        # client.search() was removed in qdrant-client >= 1.16; query_points is
        # the supported universal query API.
        response = await self._client.query_points(
            collection_name=self._collection,
            query=vector,
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
            for r in response.points
        ]
