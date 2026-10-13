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


class WikiExtractionOutput(BaseModel):
    """LLM Wiki 抽取结果（11-llm-wiki-spec section 4.2）。

    ``should_create=false`` 表示证据不足或无增量，调用方据此跳过沉淀；
    其余字段留空。抽取失败的隔离与重试由 ``generate_json`` 承担。
    """

    should_create: bool = False
    slug: str = ""
    title: str = ""
    summary: str = ""
    content: str = ""
    tags: list[str] = []
