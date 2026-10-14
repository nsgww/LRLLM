-- migrate_0.7.0.sql — Agent 平台：审计日志表（12-agent-platform-spec §2.5）
-- 幂等，可重复执行。

CREATE TABLE IF NOT EXISTS audit_logs (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_id         TEXT NOT NULL,
    action             TEXT NOT NULL,
    resource_type      TEXT NOT NULL,
    resource_id        TEXT,
    knowledge_base_id  UUID,
    risk               TEXT NOT NULL DEFAULT 'low',
    decision           TEXT NOT NULL,
    requires_approval  BOOLEAN NOT NULL DEFAULT FALSE,
    approved_by        TEXT,
    detail             JSONB NOT NULL DEFAULT '{}',
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_kb_time
    ON audit_logs (knowledge_base_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_subject_time
    ON audit_logs (subject_id, created_at DESC);
