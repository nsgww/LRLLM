"""Structured LLM output schemas (08-prompt-spec section 4)."""

from pydantic import BaseModel

from app.domain.query import Intent


class QueryUnderstandingOutput(BaseModel):
    intent: Intent
    knowledge_required: bool = True
    product: str | None = None
    version: str | None = None
    entities: list[str] = []
    constraints: list[str] = []


class QueryRewriteOutput(BaseModel):
    rewritten_query: str


class SubQueryOutput(BaseModel):
    id: str
    query: str
    product: str | None = None
    version: str | None = None


class QueryDecompositionOutput(BaseModel):
    sub_queries: list[SubQueryOutput]
