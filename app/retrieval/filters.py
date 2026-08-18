"""Metadata filter construction (06-retrieval-spec section 3).

knowledge_base_id always comes from the API scope contract, never from
LLM output. version becomes an exact-match filter only when the user
explicitly specified one; otherwise it stays unset so multiple versions
can participate (02 section 9).
"""

from app.domain.query import QueryUnderstanding, SubQuery
from app.domain.retrieval import MetadataFilter


def build_metadata_filter(
    knowledge_base_id: str,
    understanding: QueryUnderstanding | None = None,
    sub_query: SubQuery | None = None,
) -> MetadataFilter:
    product: str | None = None
    version: str | None = None
    if understanding is not None:
        product = understanding.product
        version = understanding.version
    if sub_query is not None:
        product = sub_query.product or product
        version = sub_query.version or version
    return MetadataFilter(
        knowledge_base_id=knowledge_base_id,
        product=product,
        version=version,
    )
