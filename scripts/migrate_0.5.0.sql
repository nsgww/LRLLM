-- Private Knowledge RAG 0.5.0 增量迁移
-- 适用对象：已按 0.4.0（或更早）建库的实例。
-- 全新部署无需执行本文件，直接跑 init_db.sql 即可（已包含以下全部内容）。
-- 幂等：可重复执行。用法：psql -d <database> -f scripts/migrate_0.5.0.sql

BEGIN;

-- 1. documents.content 改为 BYTEA
--    PDF 等二进制含 NUL 字节（0x00），写入 TEXT 列会被 PostgreSQL/asyncpg 拒绝，
--    导致上传必 500。改用 BYTEA 原样保存任意字节。
--    对既有 latin-1 文本按字节保真转换；仅当列仍是 text 时才执行，保证可重复运行。
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'documents'
      AND column_name = 'content'
      AND data_type = 'text'
  ) THEN
    ALTER TABLE documents ALTER COLUMN content TYPE BYTEA USING content::bytea;
  END IF;
END $$;

-- 2. chunks.parent_chunk_id 外键加 ON DELETE CASCADE
--    软删除物理清理按批硬删父子块时，父块先删会让仍存在的子块触发 FK 违规。
--    默认约束名为 chunks_parent_chunk_id_fkey；已是 CASCADE 则跳过（幂等）。
DO $$
DECLARE
  v_conname text := 'chunks_parent_chunk_id_fkey';
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = v_conname AND contype = 'f'
  ) THEN
    IF EXISTS (
      SELECT 1 FROM pg_constraint
      WHERE conname = v_conname AND contype = 'f' AND confdeltype <> 'c'
    ) THEN
      EXECUTE format('ALTER TABLE chunks DROP CONSTRAINT %I', v_conname);
      EXECUTE format(
        'ALTER TABLE chunks ADD CONSTRAINT %I FOREIGN KEY (parent_chunk_id) REFERENCES chunks(id) ON DELETE CASCADE',
        v_conname
      );
    END IF;
  ELSE
    EXECUTE format(
      'ALTER TABLE chunks ADD CONSTRAINT %I FOREIGN KEY (parent_chunk_id) REFERENCES chunks(id) ON DELETE CASCADE',
      v_conname
    );
  END IF;
END $$;

COMMIT;
