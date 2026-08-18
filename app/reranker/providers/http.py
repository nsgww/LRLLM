"""Generic HTTP reranker provider.

Expects the common rerank API shape (TEI / Jina / Cohere style):
POST {base_url}/rerank {"model", "query", "documents", "top_n"}
-> {"results": [{"index": int, "relevance_score": float}]}
"""

import httpx

from app.reranker.interface import RerankResult


class HttpReranker:
    def __init__(
        self,
        base_url: str,
        model: str = "",
        api_key: str = "",
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.AsyncClient(timeout=timeout, headers=headers)

    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_k: int,
    ) -> list[RerankResult]:
        payload = {
            "query": query,
            "documents": documents,
            "top_n": top_k,
        }
        if self._model:
            payload["model"] = self._model
        response = await self._client.post(f"{self._base_url}/rerank", json=payload)
        response.raise_for_status()
        results = response.json().get("results", [])
        return [
            RerankResult(index=item["index"], score=float(item["relevance_score"]))
            for item in results[:top_k]
        ]

    async def aclose(self) -> None:
        await self._client.aclose()
