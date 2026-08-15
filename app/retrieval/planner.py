"""Retrieval planning: intent -> strategy (02 section 7, 06 section 12).

Strategies are dynamically selected by intent; parameters always come
from settings, never hardcoded.
"""

from dataclasses import dataclass

from app.core.config import Settings
from app.domain.query import Intent


@dataclass(frozen=True)
class RetrievalStrategy:
    name: str
    top_k_vector: int
    top_k_keyword: int
    use_reranker: bool = True
    decompose: bool = False
    needs_rag: bool = True


def plan(intent: Intent, settings: Settings) -> RetrievalStrategy:
    base = dict(
        top_k_vector=settings.top_k_vector,
        top_k_keyword=settings.top_k_keyword,
    )
    match intent:
        case Intent.EXACT_QA | Intent.CAPABILITY | Intent.CONCEPT | Intent.DOCUMENT_ANALYSIS:
            return RetrievalStrategy(name="hybrid_rerank", **base)
        case Intent.HOW_TO:
            return RetrievalStrategy(name="hybrid_rerank", **base)
        case Intent.SUMMARY:
            return RetrievalStrategy(
                name="multi_section",
                top_k_vector=settings.top_k_vector * 2,
                top_k_keyword=settings.top_k_keyword * 2,
            )
        case Intent.COMPARISON:
            return RetrievalStrategy(name="decompose", decompose=True, **base)
        case Intent.GENERAL_KNOWLEDGE | Intent.TOOL_ACTION:
            # tools are out of v0.1 scope; both answer without RAG
            return RetrievalStrategy(
                name="no_rag",
                needs_rag=False,
                use_reranker=False,
                top_k_vector=0,
                top_k_keyword=0,
            )
    return RetrievalStrategy(name="hybrid_rerank", **base)
