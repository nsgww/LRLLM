"""Structured prompt output validation / retry / fallback (08 section 5, 10 section 7).

These are pure unit tests: a fake LLM drives ``generate_json`` and the
evidence checker so the retry-then-fallback contract is verified without a
network or database.
"""

import pytest

from app.core.errors import AppError, QueryStage
from app.domain.retrieval import EvidenceStatus, RankedChunk
from app.llm.parsing import generate_json
from app.llm.schemas import QueryUnderstandingOutput

pytestmark = pytest.mark.asyncio


class ScriptedLLM:
    """Returns queued responses in order; records every call."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[list[dict]] = []

    async def generate(self, messages, **kwargs) -> str:
        self.calls.append(messages)
        if not self._responses:
            raise AssertionError("ScriptedLLM ran out of responses")
        return self._responses.pop(0)


async def test_valid_json_parses_without_retry():
    llm = ScriptedLLM(['{"intent": "how_to", "knowledge_required": true}'])
    out = await generate_json(llm, [{"role": "system", "content": "x"}],
                              QueryUnderstandingOutput, QueryStage.QUERY_UNDERSTANDING)
    assert out.intent.value == "how_to"
    assert len(llm.calls) == 1


async def test_invalid_then_valid_retries_once():
    llm = ScriptedLLM([
        "not json at all",
        '{"intent": "exact_qa", "knowledge_required": true}',
    ])
    out = await generate_json(llm, [{"role": "system", "content": "x"}],
                              QueryUnderstandingOutput, QueryStage.QUERY_UNDERSTANDING)
    assert out.intent.value == "exact_qa"
    assert len(llm.calls) == 2, "must retry exactly once with the error"


async def test_invalid_twice_raises_stage_error():
    llm = ScriptedLLM(["nope", "still nope"])
    with pytest.raises(AppError) as exc:
        await generate_json(llm, [{"role": "system", "content": "x"}],
                            QueryUnderstandingOutput, QueryStage.QUERY_UNDERSTANDING)
    assert exc.value.code == "LLM_OUTPUT_INVALID"
    assert exc.value.stage == QueryStage.QUERY_UNDERSTANDING.value


async def test_code_fenced_json_is_extracted():
    llm = ScriptedLLM(['```json\n{"intent": "concept", "knowledge_required": true}\n```'])
    out = await generate_json(llm, [{"role": "system", "content": "x"}],
                              QueryUnderstandingOutput, QueryStage.QUERY_UNDERSTANDING)
    assert out.intent.value == "concept"


class _StubPrompts:
    async def get(self, key, version=None):
        from app.llm.prompts.loader import PromptTemplate

        return PromptTemplate(key=key, version=1, content="{{query}}{{chunks}}",
                              variables=["query", "chunks"])


async def test_evidence_check_falls_back_to_insufficient():
    """08 section 5 / Non-Negotiable #5: failure converges to INSUFFICIENT."""
    from app.retrieval.evidence import EvidenceChecker

    llm = ScriptedLLM(["garbage", "garbage again"])
    checker = EvidenceChecker(llm, _StubPrompts())
    chunk = RankedChunk(
        chunk_id="c1", document_id="d1", text="product supports oauth",
        score=1.0, heading_path="p", line_start=1, line_end=2,
        product="MCP", version="0.5.3",
    )
    result = await checker.check("does it support oauth 2.0?", [chunk])
    assert result.status == EvidenceStatus.INSUFFICIENT


async def test_evidence_check_drops_unknown_supporting_ids():
    """supporting_chunk_ids may only reference chunks actually provided."""
    from app.retrieval.evidence import EvidenceChecker

    llm = ScriptedLLM([
        '{"status": "SUPPORTED", "reason": "ok", "supporting_chunk_ids": ["c1", "ghost"]}'
    ])
    checker = EvidenceChecker(llm, _StubPrompts())
    chunk = RankedChunk(
        chunk_id="c1", document_id="d1", text="evidence", score=1.0,
        heading_path="p", line_start=1, line_end=2, product="MCP", version="0.5.3",
    )
    result = await checker.check("q", [chunk])
    assert result.supporting_chunk_ids == ["c1"]
