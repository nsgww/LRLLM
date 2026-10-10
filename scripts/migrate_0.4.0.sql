-- Private Knowledge RAG 0.4.0 增量迁移
-- 适用对象：已按 0.3.0（或更早）建库的实例。
-- 全新部署无需执行本文件，直接跑 init_db.sql 即可（已包含以下全部内容）。
-- 幂等：可重复执行。用法：psql -d <database> -f scripts/migrate_0.4.0.sql

BEGIN;

-- 1. 查询轨迹增加 Agent 工具调用步骤（/v1/agent 自主决策路径）
--    固定管道（/v1/query）写入 NULL，字段兼容量不受影响。
--    内容形态：[{tool, arguments, result_preview, error?}]
ALTER TABLE query_traces ADD COLUMN IF NOT EXISTS agent_steps JSONB;

COMMIT;
