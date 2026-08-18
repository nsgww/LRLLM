"""Structured LLM output parsing (08-prompt-spec section 5).

Flow: LLM output -> JSON extraction -> schema validation -> one retry
with the validation error -> stage-level failure. Callers decide the
fallback value; evidence_check must fall back conservatively.
"""

import json
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.core.errors import AppError, QueryStage
from app.llm.interface import LLM, Message

T = TypeVar("T", bound=BaseModel)


async def generate_json(
    llm: LLM,
    messages: list[Message],
    model: type[T],
    stage: QueryStage,
) -> T:
    raw = await llm.generate(messages)
    try:
        return model.model_validate(_extract_json(raw))
    except (json.JSONDecodeError, ValidationError, ValueError) as first_error:
        retry_messages = [
            *messages,
            {"role": "assistant", "content": raw},
            {
                "role": "user",
                "content": (
                    "Your previous output was not valid JSON for the required schema. "
                    f"Error: {first_error}. Reply with corrected JSON only."
                ),
            },
        ]
        raw_retry = await llm.generate(retry_messages)
        try:
            return model.model_validate(_extract_json(raw_retry))
        except (json.JSONDecodeError, ValidationError, ValueError) as second_error:
            raise AppError(
                code="LLM_OUTPUT_INVALID",
                message=f"structured output invalid after retry: {second_error}",
                stage=stage,
            ) from second_error


def _extract_json(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:] if lines and lines[0].startswith("```") else lines
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("LLM output JSON is not an object")
    return parsed
