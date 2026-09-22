"""Reranker invocation (06-retrieval-spec section 7).

The reranker may only reorder candidates. Any failure or contract
violation falls back to RRF order, and the fallback is recorded in Trace.
"""

import logging
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.domain.retrieval import RankedChunk
from app.reranker.interface import Reranker
from app.storage.postgres.repositories import ChunkRepository

logger = logging.getLogger(__name__)


@dataclass
class RerankOutcome:
    chunks: list[RankedChunk] = field(default_factory=list)
    fallback: bool = False


class RerankService:
    def __init__(
        self,
        reranker: Reranker | None,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self._reranker = reranker
        self._session_factory = session_factory
        self._settings = settings

    async def rerank(
        self,
        query: str,
        candidates: list[tuple[str, float]],
        sub_query_id: str | None = None,
    ) -> RerankOutcome:
        if not candidates:
            return RerankOutcome()

        candidate_ids = [cid for cid, _ in candidates]
        rrf_scores = dict(candidates)
        async with self._session_factory() as session:
            # require_ready: vector recall may surface points whose document is
            # still PROCESSING/FAILED; only READY documents may be served.
            chunks = ChunkRepository(session)
            rows = await chunks.get_many(candidate_ids, require_ready=True)
            # 04 节 17.1：命中子块后在 Context 中扩展为父块全文；父块只存
            # PostgreSQL，此处一次性批量取回，避免逐块查询。
            parent_ids = {str(r.parent_chunk_id) for r in rows if r.parent_chunk_id}
            parents = await chunks.get_many(list(parent_ids)) if parent_ids else []
        parent_text_by_id = {str(p.id): (p.raw_content or p.text) for p in parents}
        rows_by_id = {str(r.id): r for r in rows}
        ordered_rows = [rows_by_id[cid] for cid in candidate_ids if cid in rows_by_id]

        if self._reranker is not None:
            try:
                results = await self._reranker.rerank(
                    query,
                    [r.text for r in ordered_rows],
                    top_k=self._settings.rerank_top_n,
                )
                if not all(0 <= r.index < len(ordered_rows) for r in results):
                    raise ValueError("reranker returned out-of-range index")
                return RerankOutcome(
                    chunks=[
                        _to_ranked(
                            ordered_rows[r.index],
                            r.score,
                            sub_query_id,
                            parent_text_by_id,
                        )
                        for r in results
                    ]
                )
            except Exception:
                # degrade to RRF order (flagged below), but keep the reason visible
                logger.warning("reranker failed; falling back to RRF order", exc_info=True)

        top_n = self._settings.rerank_top_n
        return RerankOutcome(
            chunks=[
                _to_ranked(r, rrf_scores.get(str(r.id), 0.0), sub_query_id, parent_text_by_id)
                for r in ordered_rows[:top_n]
            ],
            fallback=self._reranker is not None,
        )


def _to_ranked(
    row,
    score: float,
    sub_query_id: str | None,
    parent_text_by_id: dict[str, str] | None = None,
) -> RankedChunk:
    parent_id = str(row.parent_chunk_id) if row.parent_chunk_id else None
    return RankedChunk(
        chunk_id=str(row.id),
        document_id=str(row.document_id),
        text=row.text,
        score=score,
        heading_path=row.heading_path,
        line_start=row.line_start,
        line_end=row.line_end,
        chunk_type=row.chunk_type.value,
        raw_content=row.raw_content,
        parent_chunk_id=parent_id,
        parent_content=(parent_text_by_id or {}).get(parent_id) if parent_id else None,
        product=row.product,
        version=row.version,
        sub_query_id=sub_query_id,
    )
