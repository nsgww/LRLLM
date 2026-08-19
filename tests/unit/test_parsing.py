"""Structured LLM output parsing contract tests (08 section 5)."""

import pytest

from app.core.errors import AppError, QueryStage
from app.llm.parsing import _extract_json, generate_json
from app.llm.schemas import QueryUnderstandingOutput

VALID = '{"intent": "how_to", "knowledge_required": true, "product": "MCP"}'


class FakeLLM:
    def __init__(self, outputs: list[str]) -> None:
        self._outputs = list(outputs)
        self.calls = 0

    async def generate(self, messages, **kwargs):
        self.calls += 1
        return self._outputs.pop(0)


def _messages():
    return [{"role": "user", "content": "classify"}]


async def test_valid_output_parsed_without_retry():
    llm = FakeLLM([VALID])
    result = await generate_json(
        llm, _messages(), QueryUnderstandingOutput, QueryStage.QUERY_UNDERSTANDING
    )
    assert result.intent.value == "how_to"
    assert result.product == "MCP"
    assert llm.calls == 1


async def test_invalid_output_retried_once_then_succeeds():
    llm = FakeLLM(["not json at all", VALID])
    result = await generate_json(
        llm, _messages(), QueryUnderstandingOutput, QueryStage.QUERY_UNDERSTANDING
    )
    assert result.intent.value == "how_to"
    assert llm.calls == 2


async def test_invalid_after_retry_raises_stage_error():
    llm = FakeLLM(["garbage", "still garbage"])
    with pytest.raises(AppError) as exc_info:
        await generate_json(
            llm, _messages(), QueryUnderstandingOutput, QueryStage.QUERY_UNDERSTANDING
        )
    assert exc_info.value.code == "LLM_OUTPUT_INVALID"
    assert exc_info.value.stage == "QUERY_UNDERSTANDING"
    assert llm.calls == 2


async def test_schema_violation_triggers_retry():
    llm = FakeLLM(['{"intent": "not_an_intent"}', VALID])
    result = await generate_json(
        llm, _messages(), QueryUnderstandingOutput, QueryStage.QUERY_UNDERSTANDING
    )
    assert result.intent.value == "how_to"


def test_extract_json_handles_code_fence():
    raw = "```json\n" + VALID + "\n```"
    assert _extract_json(raw)["intent"] == "how_to"


def test_extract_json_handles_surrounding_prose():
    raw = "Here is the result:\n" + VALID + "\nHope that helps."
    assert _extract_json(raw)["product"] == "MCP"


def test_extract_json_rejects_non_object():
    with pytest.raises(ValueError):
        _extract_json("[1, 2, 3]")
