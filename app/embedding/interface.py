"""Embedding interface (03-technology-selection section 5).

The embedding model is never exposed directly to business code.
"""

from typing import Protocol


class EmbeddingModel(Protocol):
    @property
    def model_name(self) -> str:
        ...

    @property
    def model_version(self) -> str:
        ...

    @property
    def dimension(self) -> int:
        ...

    async def embed_documents(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        ...

    async def embed_query(
        self,
        query: str,
    ) -> list[float]:
        ...
