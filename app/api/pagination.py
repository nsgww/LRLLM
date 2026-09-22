"""Cursor pagination contract (05-api-spec section 12).

List endpoints return `{items, next_cursor, has_more}`. Cursors are opaque to
clients and encode the keyset `(created_at, id)` the next page starts after.
"""

import base64
import binascii
import json
from datetime import datetime

from app.core.errors import AppError


def encode_cursor(created_at: datetime, item_id: str) -> str:
    raw = json.dumps(
        {"ts": created_at.isoformat(), "id": item_id}, separators=(",", ":")
    )
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8"))
        return datetime.fromisoformat(data["ts"]), str(data["id"])
    except (binascii.Error, ValueError, KeyError, TypeError, UnicodeDecodeError) as exc:
        raise AppError(
            code="INVALID_CURSOR",
            message="cursor is invalid or malformed",
            http_status=400,
        ) from exc


def next_cursor(rows: list, has_more: bool) -> str | None:
    """Cursor pointing past the last row of the current page."""
    if not has_more or not rows:
        return None
    last = rows[-1]
    return encode_cursor(last.created_at, str(last.id))
