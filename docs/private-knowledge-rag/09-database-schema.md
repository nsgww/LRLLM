---
name: private-knowledge-rag-database-schema
version: 0.1.0
description: 私有知识库 RAG PostgreSQL DDL 与 Qdrant Collection 定义
---

# Private Knowledge RAG Database Schema

## 1. 范围与原则

- 本文档的 DDL 可以直接执行建库。
- PostgreSQL 是 Document / Section / Chunk 的唯一 Source of Truth。
- Qdrant 只保存 Vector + Retrieval Metadata，可通过对 Chunk 重新 Embedding 完整重建。
- Chunk 表不存向量本体，只记录 `embedding_model / embedding_model_version`。
- 删除采用 Soft Delete（`deleted_at`），物理清理由后台任务执行。
- `knowledge_base_id` 在 Document / Section / Chunk / Job / Trace 上冗余存储，保证任意查询都能强制作用域过滤。
- v0.1 为单一共享知识空间，不设租户表；未来如需多租户，`tenant_id` 作为新列加入各表与 Qdrant Payload，现有结构不需要重构。

## 2. 扩展

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- CJK / 专有术语文本兜底检索
```

## 3. 枚举类型

```sql
CREATE TYPE document_status AS ENUM (
    'PENDING', 'PROCESSING', 'READY', 'FAILED', 'CONFLICT'
);

CREATE TYPE job_status AS ENUM (
    'PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED'
);

CREATE TYPE chunk_type AS ENUM (
    'TEXT', 'CODE', 'TABLE', 'LIST'
);

CREATE TYPE evidence_status AS ENUM (
    'SUPPORTED', 'PARTIALLY_SUPPORTED', 'INSUFFICIENT', 'CONTRADICTED'
);

CREATE TYPE prompt_status AS ENUM (
    'DRAFT', 'PUBLISHED', 'ARCHIVED'
);

CREATE TYPE message_role AS ENUM (
    'USER', 'ASSISTANT', 'SYSTEM'
);
```

## 4. DDL

```sql
CREATE TABLE knowledge_bases (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    description TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at  TIMESTAMPTZ
);

CREATE UNIQUE INDEX uq_kb_name
    ON knowledge_bases (name)
    WHERE deleted_at IS NULL;

CREATE TABLE documents (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    knowledge_base_id      UUID NOT NULL REFERENCES knowledge_bases(id),
    title                  TEXT NOT NULL,
    doc_class              TEXT,
    source                 TEXT,
    product                TEXT,
    version                TEXT,
    content                TEXT NOT NULL,
    content_hash           TEXT NOT NULL,
    parser_version         TEXT,
    chunker_version        TEXT,
    embedding_model        TEXT,
    embedding_model_version TEXT,
    processing_fingerprint TEXT,
    status                 document_status NOT NULL DEFAULT 'PENDING',
    error_code             TEXT,
    error_message          TEXT,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at             TIMESTAMPTZ
);

-- 同一知识库内相同内容只允许存在一个未删除 Document（04 节 Content Hash Skip 的存储层保障）
CREATE UNIQUE INDEX uq_document_kb_hash
    ON documents (knowledge_base_id, content_hash)
    WHERE deleted_at IS NULL;

CREATE INDEX idx_documents_kb_status
    ON documents (knowledge_base_id, status)
    WHERE deleted_at IS NULL;

CREATE INDEX idx_documents_product_version
    ON documents (knowledge_base_id, product, version)
    WHERE deleted_at IS NULL;

CREATE TABLE sections (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id       UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    parent_section_id UUID REFERENCES sections(id),
    heading           TEXT NOT NULL,
    heading_path      TEXT NOT NULL,
    level             INT NOT NULL,
    section_order     INT NOT NULL,
    line_start        INT NOT NULL,
    line_end          INT NOT NULL
);

CREATE INDEX idx_sections_document ON sections (document_id, section_order);

CREATE TABLE chunks (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    knowledge_base_id      UUID NOT NULL,
    document_id            UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    section_id             UUID REFERENCES sections(id),
    text                   TEXT NOT NULL,
    raw_content            TEXT,          -- Table 原始表示，最终 Context 使用
    heading_path           TEXT NOT NULL,
    line_start             INT NOT NULL,
    line_end               INT NOT NULL,
    chunk_type             chunk_type NOT NULL DEFAULT 'TEXT',
    chunk_index            INT NOT NULL,
    token_count            INT NOT NULL,
    content_hash           TEXT NOT NULL,
    product                TEXT,          -- 冗余自 Document，用于过滤
    version                TEXT,          -- 冗余自 Document，用于过滤
    embedding_model        TEXT,
    embedding_model_version TEXT,
    search_tsv             TSVECTOR,      -- 由触发器维护
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at             TIMESTAMPTZ
);

CREATE INDEX idx_chunks_document ON chunks (document_id, chunk_index)
    WHERE deleted_at IS NULL;

CREATE INDEX idx_chunks_kb ON chunks (knowledge_base_id)
    WHERE deleted_at IS NULL;

CREATE INDEX idx_chunks_product_version ON chunks (knowledge_base_id, product, version)
    WHERE deleted_at IS NULL;

CREATE INDEX idx_chunks_tsv ON chunks USING GIN (search_tsv);

CREATE INDEX idx_chunks_text_trgm ON chunks USING GIN (text gin_trgm_ops);

CREATE INDEX idx_chunks_heading_trgm ON chunks USING GIN (heading_path gin_trgm_ops);
```

## 5. 全文检索向量维护

加权 tsvector：标题路径与产品 / 版本权重高于正文。

```sql
CREATE OR REPLACE FUNCTION chunks_search_tsv_trigger() RETURNS trigger AS $$
BEGIN
    NEW.search_tsv :=
        setweight(to_tsvector('simple', coalesce(NEW.heading_path, '')), 'A') ||
        setweight(to_tsvector('simple', coalesce(NEW.product, '')), 'A') ||
        setweight(to_tsvector('simple', coalesce(NEW.version, '')), 'A') ||
        setweight(to_tsvector('simple', coalesce(NEW.text, '')), 'B');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_chunks_search_tsv
    BEFORE INSERT OR UPDATE OF text, heading_path, product, version
    ON chunks
    FOR EACH ROW
    EXECUTE FUNCTION chunks_search_tsv_trigger();
```

说明：

- `simple` 配置不分词，配合 `pg_trgm` 索引覆盖中文与 API 名 / 错误码 / 版本号等专有术语。
- 未来可替换为 zhparser 等中文分词配置，触发器签名不变。

## 6. Ingestion Job

```sql
CREATE TABLE ingestion_jobs (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    knowledge_base_id UUID NOT NULL,
    document_id       UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    status            job_status NOT NULL DEFAULT 'PENDING',
    stage             TEXT,               -- PARSE / CHUNK / EMBEDDING / VECTOR_INDEX / KEYWORD_INDEX ...
    parser            TEXT,
    parser_version    TEXT,
    content_hash      TEXT,
    section_count     INT,
    chunk_count       INT,
    embedding_count   INT,
    error_code        TEXT,
    error_message     TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at        TIMESTAMPTZ,
    finished_at       TIMESTAMPTZ
);

CREATE INDEX idx_jobs_document ON ingestion_jobs (document_id, created_at DESC);

CREATE INDEX idx_jobs_status ON ingestion_jobs (status)
    WHERE status IN ('PENDING', 'RUNNING');
```

## 7. Conversation

```sql
CREATE TABLE conversations (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    knowledge_base_id UUID NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE conversation_messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            message_role NOT NULL,
    content         TEXT NOT NULL,
    answer_id       UUID,               -- ASSISTANT 消息对应的回答标识
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_messages_conversation
    ON conversation_messages (conversation_id, created_at);
```

## 8. Query Trace

Retrieval Trace 只进本表，不对公开 API 暴露（见 `05-api-spec.md` 第 11 节）。

```sql
CREATE TABLE query_traces (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    knowledge_base_id    UUID NOT NULL,
    conversation_id      UUID REFERENCES conversations(id),
    answer_id            UUID NOT NULL,
    raw_query            TEXT NOT NULL,
    rewritten_query      TEXT,
    intent               TEXT,
    product              TEXT,
    version              TEXT,
    sub_queries          JSONB,
    retrieval_strategy   TEXT,
    metadata_filters     JSONB NOT NULL,
    vector_results       JSONB,
    keyword_results      JSONB,
    fused_candidates     JSONB,
    reranked_results     JSONB,
    reranker_fallback    BOOLEAN NOT NULL DEFAULT false,
    evidence_status      evidence_status,
    evidence_results     JSONB,
    selected_chunks      JSONB,         -- document_id / chunk_id / version / heading_path / line range
    context_token_count  INT,
    final_answer         TEXT,
    prompt_versions      JSONB,         -- {key: version}
    error_stage          TEXT,
    latency_ms           INT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_traces_kb_time ON query_traces (knowledge_base_id, created_at DESC);

CREATE INDEX idx_traces_answer ON query_traces (answer_id);
```

## 9. Prompt Template

```sql
CREATE TABLE prompt_templates (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key        TEXT NOT NULL,
    version    INT NOT NULL,
    content    TEXT NOT NULL,
    variables  JSONB NOT NULL DEFAULT '[]',
    status     prompt_status NOT NULL DEFAULT 'DRAFT',
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (key, version)
);

-- 同一 key 只允许一个 PUBLISHED 版本
CREATE UNIQUE INDEX uq_prompt_published
    ON prompt_templates (key)
    WHERE status = 'PUBLISHED';
```

## 10. Qdrant Collection

Collection 定义（通过 Qdrant API 创建，此处为契约描述）：

```json
{
  "collection_name": "chunks_v1",
  "vectors": {
    "size": "<embedding_dimension>",
    "distance": "Cosine"
  }
}
```

Payload 字段（每个 Point 必带）：

```json
{
  "knowledge_base_id": "uuid",
  "document_id": "uuid",
  "section_id": "uuid",
  "chunk_id": "uuid",
  "product": "MCP",
  "version": "0.5.3",
  "chunk_type": "TEXT"
}
```

必须为以下字段建立 Payload Index（keyword 类型），保证 filter 在存储层执行：

```text
knowledge_base_id
document_id
product
version
chunk_type
```

规则：

- Point ID 使用 `chunk_id`，保证可按 Chunk 精确删除与对账。
- `embedding_dimension` 变化（换 Embedding Model）必须新建 Collection（如 `chunks_v2`），不得在原地混存不同维度向量。
- Qdrant 中的数据必须能由 PostgreSQL 的 `chunks` 表完整重建。

## 11. 数据边界与一致性

```text
PostgreSQL                    Qdrant
knowledge_bases
documents
sections
chunks          <- chunk_id ->  Vector Point
ingestion_jobs
query_traces
prompt_templates
```

- 写入顺序：先 PostgreSQL Chunk，后 Qdrant Point；Document 只有两侧都成功才进入 `READY`（见 `04-ingestion-pipeline-spec.md` 第 34 节）。
- 删除顺序：先 Soft Delete（Retrieval 立即不可见），后台任务再清理 Qdrant Point 与物理行。
- 对账方式：以 `chunks.id` 集合为准，比对 Qdrant Point ID 集合，发现孤儿 Point 由后台任务清理。

## 12. Non-Negotiable

1. PostgreSQL 是唯一 Source of Truth，Qdrant 必须可重建。
2. 所有知识数据表必须带 `knowledge_base_id`，Chunks 同时冗余 `product / version`。
3. DDL 必须可直接执行，本文档即建库契约。
4. Qdrant Payload 中的过滤字段必须建 Payload Index，filter 在存储层执行。
5. 删除必须先 Soft Delete 立即可见生效，物理清理异步。
6. Embedding 维度变化必须新建 Collection，不得混存。
7. `prompt_templates` 同一 key 只能有一个 PUBLISHED 版本（由部分唯一索引强制）。
8. `query_traces` 必须能完整回放一次请求，字段与 `02-query-rag-spec.md` 第 20 节对齐。
9. 同一知识库内相同 `content_hash` 的未删除 Document 只能有一个。
10. Chunk 必须能通过 `document_id / section_id` 回溯父级，不允许孤儿 Chunk。
