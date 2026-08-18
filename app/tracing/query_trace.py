"""Retrieval Trace assembly (02-query-rag-spec section 20, 09 section 8).

Every request must be replayable from its trace: why these chunks were
sent to the LLM, which filters applied, which prompts and versions ran.
"""

import uuid
from dataclasses import dataclass, field

from app.domain.retrieval import EvidenceResult, RankedChunk, RetrievalHit
from app.llm.prompts.loader import PromptTemplate


@dataclass
class QueryTraceBuilder:
    knowledge_base_id: str
    answer_id: str
    raw_query: str
    conversation_id: str | None = None
    rewritten_query: str | None = None
    intent: str | None = None
    product: str | None = None
    version: str | None = None
    sub_queries: list[dict] = field(default_factory=list)
    retrieval_strategy: str | None = None
    metadata_filters: list[dict] = field(default_factory=list)
    vector_results: dict = field(default_factory=dict)
    keyword_results: dict = field(default_factory=dict)
    fused_candidates: dict = field(default_factory=dict)
    reranked_results: dict = field(default_factory=dict)
    reranker_fallback: bool = False
    evidence_status: str | None = None
    evidence_results: dict = field(default_factory=dict)
    selected_chunks: list[dict] = field(default_factory=list)
    context_token_count: int | None = None
    final_answer: str | None = None
    prompt_versions: dict = field(default_factory=dict)
    fallbacks: list[str] = field(default_factory=list)
    error_stage: str | None = None
    latency_ms: int | None = None

    def record_prompt(self, template: PromptTemplate) -> None:
        self.prompt_versions[template.key] = template.version

    def record_fallback(self, stage: str) -> None:
        self.fallbacks.append(stage)

    def record_retrieval(
        self,
        sub_query_id: str,
        vector_hits: list[RetrievalHit],
        keyword_hits: list[RetrievalHit],
        candidates: list[tuple[str, float]],
        degraded: list[str],
    ) -> None:
        self.vector_results[sub_query_id] = _hits(vector_hits)
        self.keyword_results[sub_query_id] = _hits(keyword_hits)
        self.fused_candidates[sub_query_id] = {
            "count": len(candidates),
            "degraded": degraded,
            "items": [{"chunk_id": cid, "rrf_score": round(score, 6)} for cid, score in candidates],
        }

    def record_reranked(self, sub_query_id: str, chunks: list[RankedChunk]) -> None:
        self.reranked_results[sub_query_id] = [
            {"chunk_id": c.chunk_id, "score": round(c.score, 6), "version": c.version}
            for c in chunks
        ]

    def record_evidence(self, evidence: EvidenceResult) -> None:
        self.evidence_status = evidence.status.value
        self.evidence_results = {
            "reason": evidence.reason,
            "supporting_chunk_ids": evidence.supporting_chunk_ids,
            "fallbacks": self.fallbacks,
        }

    def record_selected(self, chunks: list[RankedChunk]) -> None:
        self.selected_chunks = [
            {
                "document_id": c.document_id,
                "chunk_id": c.chunk_id,
                "product": c.product,
                "version": c.version,
                "heading_path": c.heading_path,
                "line_start": c.line_start,
                "line_end": c.line_end,
            }
            for c in chunks
        ]

    def to_row(self) -> dict:
        return {
            "id": uuid.uuid4(),
            "knowledge_base_id": uuid.UUID(self.knowledge_base_id),
            "conversation_id": uuid.UUID(self.conversation_id) if self.conversation_id else None,
            "answer_id": uuid.UUID(self.answer_id),
            "raw_query": self.raw_query,
            "rewritten_query": self.rewritten_query,
            "intent": self.intent,
            "product": self.product,
            "version": self.version,
            "sub_queries": self.sub_queries or None,
            "retrieval_strategy": self.retrieval_strategy,
            "metadata_filters": {"items": self.metadata_filters},
            "vector_results": self.vector_results or None,
            "keyword_results": self.keyword_results or None,
            "fused_candidates": self.fused_candidates or None,
            "reranked_results": self.reranked_results or None,
            "reranker_fallback": self.reranker_fallback,
            "evidence_status": self.evidence_status,
            "evidence_results": self.evidence_results or None,
            "selected_chunks": self.selected_chunks or None,
            "context_token_count": self.context_token_count,
            "final_answer": self.final_answer,
            "prompt_versions": self.prompt_versions or None,
            "error_stage": self.error_stage,
            "latency_ms": self.latency_ms,
        }


def _hits(hits: list[RetrievalHit]) -> list[dict]:
    return [
        {
            "chunk_id": h.chunk_id,
            "document_id": h.document_id,
            "score": round(h.score, 6),
            "version": h.payload.get("version"),
            "product": h.payload.get("product"),
        }
        for h in hits
    ]
