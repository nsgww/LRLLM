-- Private Knowledge RAG 0.3.0 增量迁移
-- 适用对象：已按 0.2.0（或更早）建库的实例。
-- 全新部署无需执行本文件，直接跑 init_db.sql 即可（已包含以下全部内容）。
-- 幂等：可重复执行。用法：psql -d <database> -f scripts/migrate_0.3.0.sql

BEGIN;

-- 1. 清理查询索引
--    list_deleted_ids（CleanupService._purge_chunks 入口，每轮清理都执行）
--    的条件 deleted_at IS NOT NULL 无法命中 idx_chunks_document
--    （前导列是 document_id），软删除积压时会顺序扫全表。
CREATE INDEX IF NOT EXISTS idx_chunks_deleted
    ON chunks (deleted_at)
    WHERE deleted_at IS NOT NULL;

--    list_stale_running：status = 'RUNNING' AND started_at < cutoff。
--    idx_jobs_status 只覆盖 status，started_at 范围靠回表过滤。
CREATE INDEX IF NOT EXISTS idx_jobs_running_started
    ON ingestion_jobs (started_at)
    WHERE status = 'RUNNING';

-- 2. 父块不再构建 tsvector（关键字检索永远排除 is_parent = true）
--    省下父块在 GIN 索引中的条目与写入时的 to_tsvector 开销。
CREATE OR REPLACE FUNCTION chunks_search_tsv_trigger() RETURNS trigger AS $$
BEGIN
    IF NEW.is_parent THEN
        NEW.search_tsv := NULL;
        RETURN NEW;
    END IF;
    NEW.search_tsv :=
        setweight(to_tsvector('simple', coalesce(NEW.heading_path, '')), 'A') ||
        setweight(to_tsvector('simple', coalesce(NEW.product, '')), 'A') ||
        setweight(to_tsvector('simple', coalesce(NEW.version, '')), 'A') ||
        setweight(to_tsvector('simple', coalesce(NEW.text, '')), 'B');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 回填：把已存在的父块的 search_tsv 清空，回收 GIN 索引空间。
-- 只触碰 is_parent = true 的行，不影响子块检索。
UPDATE chunks SET search_tsv = NULL WHERE is_parent AND search_tsv IS NOT NULL;

-- 3. 查询轨迹增加分阶段耗时（06 节 13：per_stage_latency）
ALTER TABLE query_traces ADD COLUMN IF NOT EXISTS stage_latencies JSONB;

COMMIT;
