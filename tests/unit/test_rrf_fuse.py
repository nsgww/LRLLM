"""RRF fusion contract tests (06 section 6)."""

from app.domain.retrieval import RetrievalHit, RetrievalSource
from app.retrieval.hybrid import rrf_fuse


def _hit(chunk_id: str, source: RetrievalSource) -> RetrievalHit:
    return RetrievalHit(chunk_id=chunk_id, document_id="doc", score=1.0, source=source)


def test_rrf_scores_sum_across_lists():
    vector = [_hit("A", RetrievalSource.VECTOR), _hit("B", RetrievalSource.VECTOR)]
    keyword = [_hit("B", RetrievalSource.KEYWORD), _hit("C", RetrievalSource.KEYWORD)]

    fused = rrf_fuse(vector, keyword, rrf_k=60, limit=10)
    scores = dict(fused)

    assert scores["A"] == 1.0 / 61
    assert scores["B"] == 1.0 / 62 + 1.0 / 61
    assert scores["C"] == 1.0 / 62
    # chunk in both lists wins
    assert [chunk_id for chunk_id, _ in fused] == ["B", "A", "C"]


def test_rrf_dedups_by_chunk_id():
    vector = [_hit("A", RetrievalSource.VECTOR)]
    keyword = [_hit("A", RetrievalSource.KEYWORD)]
    fused = rrf_fuse(vector, keyword, rrf_k=60, limit=10)
    assert len(fused) == 1


def test_rrf_respects_limit():
    vector = [_hit(f"V{i}", RetrievalSource.VECTOR) for i in range(5)]
    keyword = [_hit(f"K{i}", RetrievalSource.KEYWORD) for i in range(5)]
    fused = rrf_fuse(vector, keyword, rrf_k=60, limit=3)
    assert len(fused) == 3


def test_rrf_single_path_still_ranks():
    fused = rrf_fuse([_hit("A", RetrievalSource.VECTOR)], [], rrf_k=60, limit=10)
    assert fused == [("A", 1.0 / 61)]
