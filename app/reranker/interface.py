"""Reranker interface (03-technology-selection section 7).

The reranker improves precision. It may only reorder candidates,
never add or remove them (06-retrieval-spec section 7).
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass
class RerankResult:
    index: int  # index into the input documents list
    score: float


class Reranker(Protocol):
    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_k: int,
    ) -> list[RerankResult]:
        ...
