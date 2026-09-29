-- Private Knowledge RAG 0.2.0 增量迁移
-- 适用对象：用旧版 scripts/init_db.sql 建好的库（缺父子分块与任务重试字段）。
-- 全新部署无需执行本文件，直接跑 init_db.sql 即可（已包含以下全部内容）。
-- 幂等：可重复执行。用法：psql -d <database> -f scripts/migrate_0.2.0.sql

BEGIN;

-- 1. 父子分块（04 节 17.1）：子块参与检索，父块只存 PG 用于上下文扩展
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS parent_chunk_id UUID REFERENCES chunks(id);
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS is_parent BOOLEAN NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS idx_chunks_parent
    ON chunks (parent_chunk_id)
    WHERE deleted_at IS NULL;

-- 2. 入库任务韧性（04 节 34 / 09 节 11）：退避重试与崩溃回收
ALTER TABLE ingestion_jobs ADD COLUMN IF NOT EXISTS attempt_count INT NOT NULL DEFAULT 0;
ALTER TABLE ingestion_jobs ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_jobs_pending_due
    ON ingestion_jobs (next_attempt_at, created_at)
    WHERE status = 'PENDING';

COMMIT;
