"""Retrieval metric helpers (07-evaluation-spec section 5)."""

from app.evaluation.scoring import mrr, precision_at_k, recall_at_k


def test_recall_at_k_counts_expected_hits():
    ranked = ["A", "B", "C", "D"]
    assert recall_at_k(ranked, ["C"], k=3) == 1.0
    assert recall_at_k(ranked, ["D"], k=3) == 0.0
    assert recall_at_k(ranked, ["B", "D"], k=2) == 0.5
    assert recall_at_k(ranked, ["B", "D"], k=4) == 1.0


def test_precision_at_k_divides_by_window():
    ranked = ["A", "B", "C", "D"]
    assert precision_at_k(ranked, ["A", "C"], k=4) == 0.5
    assert precision_at_k(ranked, ["A", "C"], k=2) == 0.5
    assert precision_at_k([], ["A"], k=3) == 0.0


def test_mrr_uses_first_relevant_rank():
    assert mrr(["A", "B", "C"], ["B"]) == 0.5
    assert mrr(["A", "B", "C"], ["Z"]) == 0.0
