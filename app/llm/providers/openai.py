"""OpenAI-compatible chat completions provider (03 section 3).

Any endpoint speaking the /chat/completions protocol works here
(OpenAI, Azure-compatible gateways, local vLLM/Ollama, etc.).
"""

import json
from collections.abc import AsyncIterator

import httpx

from app.core.errors import AppError, QueryStage
from app.core.retry import with_retry
from app.llm.interface import Message


class OpenAILLM:
    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str | None = None,
        timeout: float = 120.0,
        max_attempts: int = 3,
        retry_backoff: float = 1.0,
    ) -> None:
        self._model = model
        self._base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self._max_attempts = max_attempts
        self._retry_backoff = retry_backoff
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    async def generate(self, messages: list[Message], **kwargs: object) -> str:
        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            **kwargs,
        }
        try:
            response = await with_retry(
                lambda: self._client.post(
                    f"{self._base_url}/chat/completions", json=payload
                ),
                max_attempts=self._max_attempts,
                backoff_seconds=self._retry_backoff,
                description="LLM generate",
            )
        except httpx.HTTPError as exc:
            raise AppError(
                code="LLM_REQUEST_FAILED",
                message=str(exc),
                stage=QueryStage.LLM_GENERATION,
            ) from exc
        data = response.json()
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            # 200 但响应体不合契约：给明确分类码，而不是裸 KeyError→INTERNAL_ERROR。
            raise AppError(
                code="LLM_OUTPUT_INVALID",
                message=f"unexpected response shape from LLM provider: {exc}",
                stage=QueryStage.LLM_GENERATION,
            ) from exc

    async def stream(self, messages: list[Message], **kwargs: object) -> AsyncIterator[str]:
        payload = {
            "model": self._model,
            "messages": messages,
            "stream": True,
            **kwargs,
        }
        try:
            async with self._client.stream(
                "POST", f"{self._base_url}/chat/completions", json=payload
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        return
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if content:
                        yield content
        except httpx.HTTPError as exc:
            raise AppError(
                code="LLM_STREAM_FAILED",
                message=str(exc),
                stage=QueryStage.LLM_GENERATION,
            ) from exc

    async def aclose(self) -> None:
        await self._client.aclose()
