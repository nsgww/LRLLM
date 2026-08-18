"""OpenAI-compatible embeddings provider (03 section 5)."""

import httpx

from app.core.errors import AppError


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
    ) -> None:
        self._model = model
        self._model_version = model_version
        self._dimension = dimension
        self._batch_size = batch_size
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
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = texts[start : start + self._batch_size]
            vectors.extend(await self._embed(batch))
        return vectors

    async def embed_query(self, query: str) -> list[float]:
        vectors = await self._embed([query])
        return vectors[0]

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        try:
            response = await self._client.post(
                f"{self._base_url}/embeddings",
                json={"model": self._model, "input": texts},
            )
            response.raise_for_status()
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
