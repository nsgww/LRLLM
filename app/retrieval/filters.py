"""元数据过滤器的构建（06-检索规范第3节）。

knowledge_base_id 始终来自 API 范围契约，绝不会来自
LLM 输出。version 仅在用户
明确指定时才成为精确匹配过滤器；否则它保持未设置状态，以便多个版本
均可参与（02 第9节）。
"""

from app.domain.query import QueryUnderstanding, SubQuery
from app.domain.retrieval import MetadataFilter


def build_metadata_filter(
    knowledge_base_id: str,
    understanding: QueryUnderstanding | None = None,
    sub_query: SubQuery | None = None,
    include_wiki: bool = True,
) -> MetadataFilter:
    product: str | None = None
    version: str | None = None
    if understanding is not None:
        product = understanding.product
        version = understanding.version
    if sub_query is not None:
        product = sub_query.product or product
        # 用户显式指定的 version 是硬边界，子查询不得覆盖（06 Non-Negotiable #2）；
        # 仅当用户未指定 version 时才允许子查询补充。
        version = version or sub_query.version
    return MetadataFilter(
        knowledge_base_id=knowledge_base_id,
        product=product,
        version=version,
        include_wiki=include_wiki,
    )
