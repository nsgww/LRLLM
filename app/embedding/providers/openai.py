"""OpenAI-compatible embeddings provider (03 section 5)."""

import asyncio

import httpx

from app.core.errors import AppError
from app.core.retry import with_retry


class OpenAIEmbedding:
    def __init__(
        self,
        model: str,
        model_version: str,
        dimension: int,
        api_key: str,
        base_url: str | None = None,
        timeout: float = 60.0,
        batch_size: int = 64,
        max_attempts: int = 3,
        retry_backoff: float = 1.0,
        max_concurrency: int = 4,
    ) -> None:
        self._model = model
        self._model_version = model_version
        self._dimension = dimension
        self._batch_size = batch_size
        self._max_attempts = max_attempts
        self._retry_backoff = retry_backoff
        self._max_concurrency = max(1, max_concurrency)
        self._base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def model_version(self) -> str:
        return self._model_version

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        batches = [
            texts[start : start + self._batch_size]
            for start in range(0, len(texts), self._batch_size)
        ]
        # Batches are independent; run them concurrently under a semaphore so a
        # large document does not serialize on network round trips.
        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def run(batch: list[str]) -> list[list[float]]:
            async with semaphore:
                return await self._embed(batch)

        results = await asyncio.gather(*(run(batch) for batch in batches))
        vectors: list[list[float]] = []
        for batch_vectors in results:
            vectors.extend(batch_vectors)
        return vectors

    async def embed_query(self, query: str) -> list[float]:
        vectors = await self._embed([query])
        return vectors[0]

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        try:
            response = await with_retry(
                lambda: self._client.post(
                    f"{self._base_url}/embeddings",
                    json={"model": self._model, "input": texts},
                ),
                max_attempts=self._max_attempts,
                backoff_seconds=self._retry_backoff,
                description="embedding request",
            )
        except httpx.HTTPError as exc:
            raise AppError(code="EMBEDDING_REQUEST_FAILED", message=str(exc)) from exc
        data = sorted(response.json()["data"], key=lambda item: item["index"])
        vectors = [item["embedding"] for item in data]
        for vector in vectors:
            if len(vector) != self._dimension:
                raise AppError(
                    code="EMBEDDING_DIMENSION_MISMATCH",
                    message=f"embedding dimension {len(vector)} != configured {self._dimension}",
                )
        return vectors

    async def aclose(self) -> None:
        await self._client.aclose()
