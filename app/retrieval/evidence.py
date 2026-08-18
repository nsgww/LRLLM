"""Evidence check (02-query-rag-spec section 12, 08-prompt-spec section 4.4).

- Relevance is not sufficiency; "OAuth != OAuth 2.0" cases must be
  judged INSUFFICIENT.
- The fallback converges conservatively to INSUFFICIENT (08 section 5).
- supporting_chunk_ids may only reference chunks actually provided.
"""

from pydantic import BaseModel

from app.core.errors import AppError, QueryStage
from app.domain.retrieval import EvidenceResult, EvidenceStatus, RankedChunk
from app.llm.interface import LLM
from app.llm.parsing import generate_json
from app.llm.prompts.loader import PromptLoader


class EvidenceCheckOutput(BaseModel):
    status: EvidenceStatus
    reason: str = ""
    supporting_chunk_ids: list[str] = []


class EvidenceChecker:
    def __init__(self, llm: LLM, prompts: PromptLoader) -> None:
        self._llm = llm
        self._prompts = prompts

    async def check(self, query: str, chunks: list[RankedChunk]) -> EvidenceResult:
        if not chunks:
            return EvidenceResult(
                status=EvidenceStatus.INSUFFICIENT,
                reason="no evidence retrieved",
            )

        template = await self._prompts.get("evidence_check")
        rendered = PromptLoader.render(
            template,
            {
                "query": query,
                "chunks": _format_chunks(chunks),
            },
        )
        messages = [{"role": "system", "content": rendered}]

        try:
            output = await generate_json(
                self._llm, messages, EvidenceCheckOutput, QueryStage.EVIDENCE_CHECK
            )
        except AppError:
            return EvidenceResult(
                status=EvidenceStatus.INSUFFICIENT,
                reason="evidence check output invalid; conservative fallback",
            )

        known_ids = {c.chunk_id for c in chunks}
        supporting = [cid for cid in output.supporting_chunk_ids if cid in known_ids]
        return EvidenceResult(
            status=output.status,
            reason=output.reason,
            supporting_chunk_ids=supporting,
        )


def _format_chunks(chunks: list[RankedChunk]) -> str:
    parts = []
    for c in chunks:
        header = f"[chunk_id={c.chunk_id} product={c.product} version={c.version} path={c.heading_path}]"
        parts.append(f"{header}\n{c.text}")
    return "\n\n".join(parts)
