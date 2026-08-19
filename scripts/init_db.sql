-- Private Knowledge RAG v0.1 Database Schema
-- Source: docs/private-knowledge-rag/09-database-schema.md
-- Directly executable: psql -d <database> -f scripts/init_db.sql

BEGIN;

-- 2. Extensions
CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- CJK / proper-noun fallback retrieval

-- 3. Enum types
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

-- 4. Core tables
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

-- Only one live Document per identical content within a knowledge base
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
    raw_content            TEXT,          -- original Table representation, used in final Context
    heading_path           TEXT NOT NULL,
    line_start             INT NOT NULL,
    line_end               INT NOT NULL,
    chunk_type             chunk_type NOT NULL DEFAULT 'TEXT',
    chunk_index            INT NOT NULL,
    token_count            INT NOT NULL,
    content_hash           TEXT NOT NULL,
    product                TEXT,          -- denormalized from Document for filtering
    version                TEXT,          -- denormalized from Document for filtering
    embedding_model        TEXT,
    embedding_model_version TEXT,
    search_tsv             TSVECTOR,      -- maintained by trigger
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

-- 5. Weighted tsvector maintenance
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

-- 6. Ingestion Job
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

-- 7. Conversation
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
    answer_id       UUID,               -- answer identifier of an ASSISTANT message
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_messages_conversation
    ON conversation_messages (conversation_id, created_at);

-- 8. Query Trace (internal only, never exposed via public API)
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

-- 9. Prompt Template
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

-- Only one PUBLISHED version per key
CREATE UNIQUE INDEX uq_prompt_published
    ON prompt_templates (key)
    WHERE status = 'PUBLISHED';

COMMIT;
