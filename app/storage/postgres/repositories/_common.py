"""Shared helpers for repositories (keyset pagination cursor)."""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa

from app.core.ids import parse_uuid

def _apply_cursor(
    stmt,
    model,
    cursor: tuple[datetime, str] | None,
    *,
    descending: bool,
):
    """Keyset pagination on (created_at, id); ordering must match `descending`."""
    if cursor is None:
        return stmt
    created_at, last_id = cursor
    last_uuid = parse_uuid(last_id)
    if descending:
        return stmt.where(
            sa.or_(
                model.created_at < created_at,
                sa.and_(model.created_at == created_at, model.id < last_uuid),
            )
        )
    return stmt.where(
        sa.or_(
            model.created_at > created_at,
            sa.and_(model.created_at == created_at, model.id > last_uuid),
        )
    )
