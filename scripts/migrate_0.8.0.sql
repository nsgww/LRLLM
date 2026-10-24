-- Private Knowledge RAG 0.8.0 增量迁移
-- 适用对象：已按 0.7.0（或更早）建库的实例。
-- 全新部署无需执行本文件，直接跑 init_db.sql 即可（已包含以下全部内容）。
-- 幂等：可重复执行。用法：psql -d <database> -f scripts/migrate_0.8.0.sql

BEGIN;

-- 1. wiki 列表索引与 keyset 分页排序列对齐
--    查询是 ORDER BY created_at DESC, id DESC（repositories/wiki.py，游标也用
--    created_at），旧索引建在 (knowledge_base_id, updated_at DESC) 上，
--    导致每次翻页都要对该 KB 的全部 wiki 页排序。
DROP INDEX IF EXISTS idx_wiki_pages_kb;
CREATE INDEX IF NOT EXISTS idx_wiki_pages_kb
    ON wiki_pages (knowledge_base_id, created_at DESC, id DESC)
    WHERE deleted_at IS NULL;

-- 2. 软删除 wiki 页的物理清理扫描（CleanupService._purge_wiki_pages）
CREATE INDEX IF NOT EXISTS idx_wiki_pages_deleted
    ON wiki_pages (deleted_at)
    WHERE deleted_at IS NOT NULL;

-- 3. 保留期清理按时间扫描
--    RAG_TRACE_RETENTION_DAYS / RAG_AUDIT_RETENTION_DAYS 生效后，
--    CleanupService 执行 DELETE ... WHERE created_at < cutoff ORDER BY
--    created_at LIMIT n；现有 (kb, created_at) / (subject_id, created_at)
--    索引前导列不是 created_at，无法直接服务该扫描。
CREATE INDEX IF NOT EXISTS idx_traces_created
    ON query_traces (created_at);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created
    ON audit_logs (created_at);

COMMIT;
