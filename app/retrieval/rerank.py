"""Reranker invocation (06-retrieval-spec section 7).

The reranker may only reorder candidates. Any failure or contract
violation falls back to RRF order, and the fallback is recorded in Trace.

Sub-queries share one candidate load (``load_rows``) so a multi-sub-query
query issues a single chunk SELECT instead of one per sub-query.
"""

import asyncio
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

    async def load_rows(self, candidate_ids: list[str]) -> dict[str, object]:
        """Load candidate chunk rows + parent chunk texts once, for all sub-queries.

        ``require_ready``: vector recall may surface points whose document is
        still PROCESSING/FAILED; only READY documents may be served.

        Returned mapping also carries parent rows (keyed by their own id) so
        ``rank`` can resolve ``parent_content`` without extra round-trips.
        """
        unique_ids = list(dict.fromkeys(candidate_ids))
        if not unique_ids:
            return {}
        async with self._session_factory() as session:
            chunks = ChunkRepository(session)
            rows = await chunks.get_many(unique_ids, require_ready=True)
            # 04 节 17.1：命中子块后在 Context 中扩展为父块全文；父块只存
            # PostgreSQL，此处一次性批量取回，避免逐块查询。
            parent_ids = {str(r.parent_chunk_id) for r in rows if r.parent_chunk_id}
            parents = await chunks.get_many(list(parent_ids)) if parent_ids else []
        loaded: dict[str, object] = {str(r.id): r for r in rows}
        for parent in parents:
            loaded.setdefault(str(parent.id), parent)
        return loaded

    async def rank(
        self,
        query: str,
        candidates: list[tuple[str, float]],
        rows_by_id: dict[str, object],
        sub_query_id: str | None = None,
        use_reranker: bool = True,
    ) -> RerankOutcome:
        """Rerank one sub-query against already-loaded rows.

        ``use_reranker=False`` (from the intent strategy) forces RRF order even
        when a reranker is configured, and is not counted as a fallback.
        """
        if not candidates:
            return RerankOutcome()

        candidate_ids = [cid for cid, _ in candidates]
        rrf_scores = dict(candidates)
        # 04 节 17.1：命中子块后在 Context 中扩展为父块全文；父块只存
        # PostgreSQL。父块文本由调用方按子块行一次性批量预热（见
        # ``load_parent_texts``），避免这里逐子查询重复查库。
        parent_text_by_id = _collect_parent_texts(rows_by_id, candidate_ids)
        ordered_rows = [rows_by_id[cid] for cid in candidate_ids if cid in rows_by_id]
        if not ordered_rows:
            return RerankOutcome()

        if self._reranker is not None and use_reranker:
            try:
                results = await self._reranker.rerank(
                    query,
                    [r.text for r in ordered_rows],
                    top_k=self._settings.rerank_top_n,
                )
                n = len(ordered_rows)
                # 去重：同一 index 重复出现只保留首个，避免重复 RankedChunk。
                by_index: dict[int, object] = {}
                for r in results:
                    by_index.setdefault(r.index, r)
                unique = list(by_index.values())
                if not all(0 <= r.index < n for r in unique):
                    raise ValueError("reranker returned out-of-range index")
                # 候选守恒（06 §7 / Non-Negotiable #5）：重排不得减少候选集。
                expected = min(self._settings.rerank_top_n, n)
                if len(unique) < expected:
                    raise ValueError(
                        f"reranker dropped candidates: {len(unique)} < {expected}"
                    )
                # 重排分支同样按 top_n 截断：provider 忽略 top_k 时防止候选全量下漏
                # （回退分支 131 行已有同样截断）。
                return RerankOutcome(
                    chunks=[
                        _to_ranked(
                            ordered_rows[r.index],
                            r.score,
                            sub_query_id,
                            parent_text_by_id,
                        )
                        for r in unique[: self._settings.rerank_top_n]
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
            fallback=self._reranker is not None and use_reranker,
        )

    async def rank_many(
        self,
        items: list[tuple[str, str, list[tuple[str, float]]]],
        rows_by_id: dict[str, object],
        use_reranker: bool = True,
    ) -> list[tuple[str, RerankOutcome]]:
        """Rerank several sub-queries concurrently (06 section 9).

        Returns ``(sub_query_id, outcome)`` in the input order so callers can
        keep the per-sub-query Trace grouping deterministic.
        """
        outcomes = await asyncio.gather(
            *(
                self.rank(
                    query,
                    candidates,
                    rows_by_id,
                    sub_query_id=sq_id,
                    use_reranker=use_reranker,
                )
                for sq_id, query, candidates in items
            ),
            return_exceptions=True,
        )
        results: list[tuple[str, RerankOutcome]] = []
        for (sq_id, _query, candidates), outcome in zip(items, outcomes, strict=True):
            if isinstance(outcome, BaseException):
                # The reranker already degrades internally; a raise here means
                # the fallback path itself failed (e.g. DB gone). Surface it.
                raise outcome
            results.append((sq_id, outcome))
        return results

    async def rerank(
        self,
        query: str,
        candidates: list[tuple[str, float]],
        sub_query_id: str | None = None,
    ) -> RerankOutcome:
        """Single-sub-query convenience wrapper (loads rows then ranks)."""
        rows_by_id = await self.load_rows([cid for cid, _ in candidates])
        return await self.rank(query, candidates, rows_by_id, sub_query_id=sub_query_id)


def _collect_parent_texts(
    rows_by_id: dict[str, object],
    candidate_ids: list[str],
) -> dict[str, str]:
    """Resolve parent-chunk texts for the given candidate chunk ids.

    ``rows_by_id`` holds both candidate chunks and their parent chunks (see
    ``RerankService.load_rows``); this maps parent id -> parent body so
    ``_to_ranked`` can attach ``parent_content``.
    """
    texts: dict[str, str] = {}
    for cid in candidate_ids:
        row = rows_by_id.get(cid)
        parent_id = getattr(row, "parent_chunk_id", None) if row is not None else None
        if not parent_id:
            continue
        parent = rows_by_id.get(str(parent_id))
        if parent is not None:
            texts[str(parent_id)] = parent.raw_content or parent.text
    return texts


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
