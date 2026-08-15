"""LLM interface (03-technology-selection section 3).

LLM is responsible for understanding, reasoning and generation.
It is never a source of product facts.
"""

from collections.abc import AsyncIterator
from typing import Protocol

Message = dict[str, str]  # {"role": "system" | "user" | "assistant", "content": ...}


class LLM(Protocol):
    async def generate(
        self,
        messages: list[Message],
        **kwargs: object,
    ) -> str:
        ...

    def stream(
        self,
        messages: list[Message],
        **kwargs: object,
    ) -> AsyncIterator[str]:
        """Token stream for SSE answer generation (05-api-spec section 8)."""
        ...
