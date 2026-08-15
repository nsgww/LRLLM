"""Parser interface (04-ingestion-pipeline-spec section 23)."""

from typing import Protocol

from app.domain.ingestion import DocumentAST


class Parser(Protocol):
    name: str
    version: str

    async def parse(
        self,
        source: bytes,
        metadata: dict,
    ) -> DocumentAST:
        ...
