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


class QueryUnderstandingRewriteOutput(BaseModel):
    """Fused Understanding + Rewrite output (one LLM round trip).

    Field semantics are identical to QueryUnderstandingOutput plus
    ``rewritten_query``; both fallbacks are still applied independently by the
    caller per 08 section 5.
    """

    intent: Intent
    knowledge_required: bool = True
    product: str | None = None
    version: str | None = None
    entities: list[str] = []
    constraints: list[str] = []
    rewritten_query: str = ""


class SubQueryOutput(BaseModel):
    id: str
    query: str
    product: str | None = None
    version: str | None = None


class QueryDecompositionOutput(BaseModel):
    sub_queries: list[SubQueryOutput]
