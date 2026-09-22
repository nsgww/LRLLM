"""Pipeline component versions (04-ingestion-pipeline-spec section 4/5/23).

A version bump here changes the processing fingerprint and allows reprocessing.
"""

PARSER_VERSION = "markdown-0.1.0"
HTML_PARSER_VERSION = "html-0.1.0"
PDF_PARSER_VERSION = "pdf-0.1.0"
# 0.2.0：新增父子切块结构（parent_chunk_id），指纹变化触发全量重建
CHUNKER_VERSION = "semantic-0.2.0"
