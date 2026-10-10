"""Retrieval strategy selection per intent (02 section 7, 06 section 12)."""

from app.core.config import Settings
from app.domain.query import Intent
from app.retrieval.planner import plan


def _settings() -> Settings:
    return Settings(top_k_vector=50, top_k_keyword=50)


def test_exact_qa_uses_balanced_hybrid():
    s = plan(Intent.EXACT_QA, _settings())
    assert s.name == "hybrid_rerank"
    assert s.top_k_vector == 50 and s.top_k_keyword == 50


def test_how_to_widens_keyword_recall():
    s = plan(Intent.HOW_TO, _settings())
    assert s.name == "hybrid_rerank"
    assert s.top_k_keyword == 100


def test_capability_uses_evidence_focused():
    s = plan(Intent.CAPABILITY, _settings())
    assert s.name == "evidence_focused"
    assert s.top_k_vector == 100


def test_summary_widens_both_paths():
    s = plan(Intent.SUMMARY, _settings())
    assert s.name == "multi_section"
    assert s.top_k_vector == 100 and s.top_k_keyword == 100


def test_comparison_decomposes():
    s = plan(Intent.COMPARISON, _settings())
    assert s.decompose is True


def test_general_knowledge_skips_rag():
    s = plan(Intent.GENERAL_KNOWLEDGE, _settings())
    assert s.needs_rag is False


def test_strategies_are_distinct_across_intents():
    settings = _settings()
    names = {
        plan(i, settings).name
        for i in (
            Intent.EXACT_QA,
            Intent.HOW_TO,
            Intent.CAPABILITY,
            Intent.SUMMARY,
            Intent.COMPARISON,
            Intent.GENERAL_KNOWLEDGE,
        )
    }
    # Not every intent may collapse onto the same strategy.
    assert len(names) >= 4
