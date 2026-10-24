"""baseline — 版本锚点，不含 DDL

Revision ID: 0001
Revises:
Create Date: 2026-10-24

本项目的 schema 由两条幂等 SQL 链维护：

- ``scripts/init_db.sql``：全新建库（等同 09-database-schema.md 的 DDL）
- ``scripts/migrate_<version>.sql``：已有库的增量迁移

引入这个空基线是为了让 alembic 可用，而不重复维护一份 DDL（两份 DDL 必然
漂移）。已有库标记一次即可：

    alembic stamp 0001

之后新增结构变更可以正常生成：

    alembic revision --autogenerate -m "add xxx"

约定：autogenerate 产物仅供参考，落地前仍需人工核对，并且**同时**补一个
``scripts/migrate_<version>.sql``，保持部署脚本的单一入口不被破坏。
"""

from __future__ import annotations

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No-op：schema 由 scripts/init_db.sql / migrate_*.sql 建立。"""


def downgrade() -> None:
    """No-op：基线不可回退（回退等价于删库）。"""
