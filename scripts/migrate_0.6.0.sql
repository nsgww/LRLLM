-- Private Knowledge RAG 0.6.0 增量迁移 — LLM Wiki（11-llm-wiki-spec）
-- 适用对象：已按 0.5.0（或更早）建库的实例。
-- 全新部署无需执行本文件，直接跑 init_db.sql 即可（已包含以下全部内容）。
-- 幂等：可重复执行。用法：psql -d <database> -f scripts/migrate_0.6.0.sql

BEGIN;

-- 1. wiki_status 枚举（不存在才建）
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'wiki_status') THEN
    CREATE TYPE wiki_status AS ENUM ('draft', 'published', 'archived');
  END IF;
END $$;

-- 2. documents 增加影子 document 标记列（LLM Wiki 复用检索/清理体系）
ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_type TEXT NOT NULL DEFAULT 'document';
ALTER TABLE documents ADD COLUMN IF NOT EXISTS wiki_page_id UUID;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_documents_wiki_page') THEN
    CREATE INDEX idx_documents_wiki_page ON documents (wiki_page_id) WHERE deleted_at IS NULL;
  END IF;
END $$;

-- 3. wiki_pages
CREATE TABLE IF NOT EXISTS wiki_pages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    knowledge_base_id UUID NOT NULL,
    slug            TEXT NOT NULL,
    title           TEXT NOT NULL,
    summary         TEXT NOT NULL DEFAULT '',
    status          wiki_status NOT NULL DEFAULT 'published',
    revision_count  INT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'uq_wiki_page_slug') THEN
    CREATE UNIQUE INDEX uq_wiki_page_slug
      ON wiki_pages (knowledge_base_id, slug) WHERE deleted_at IS NULL;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_wiki_pages_kb') THEN
    CREATE INDEX idx_wiki_pages_kb
      ON wiki_pages (knowledge_base_id, updated_at DESC) WHERE deleted_at IS NULL;
  END IF;
END $$;

-- 4. wiki_revisions
CREATE TABLE IF NOT EXISTS wiki_revisions (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    page_id          UUID NOT NULL REFERENCES wiki_pages(id) ON DELETE CASCADE,
    version          INT NOT NULL,
    content          TEXT NOT NULL,
    source_answer_id UUID,
    source_query     TEXT NOT NULL DEFAULT '',
    evidence         JSONB NOT NULL DEFAULT '[]',
    change_note      TEXT NOT NULL DEFAULT '',
    status           wiki_status NOT NULL DEFAULT 'published',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (page_id, version)
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_wiki_revisions_page') THEN
    CREATE INDEX idx_wiki_revisions_page ON wiki_revisions (page_id, version DESC);
  END IF;
END $$;

COMMIT;
