"""Cursor pagination helpers (05-api-spec section 12)."""

from datetime import UTC, datetime

import pytest

from app.api.pagination import decode_cursor, encode_cursor, next_cursor
from app.core.errors import AppError


class _Row:
    def __init__(self, created_at, id):
        self.created_at = created_at
        self.id = id


def test_cursor_round_trip():
    created = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    cursor = encode_cursor(created, "11111111-1111-1111-1111-111111111111")
    decoded_at, decoded_id = decode_cursor(cursor)
    assert decoded_at == created
    assert decoded_id == "11111111-1111-1111-1111-111111111111"


def test_next_cursor_is_none_without_more():
    rows = [_Row(datetime.now(UTC), "abc")]
    assert next_cursor(rows, has_more=False) is None
    assert next_cursor([], has_more=True) is None


def test_invalid_cursor_raises_classified_400():
    with pytest.raises(AppError) as exc_info:
        decode_cursor("!!!not-base64!!!")
    assert exc_info.value.http_status == 400
    assert exc_info.value.code == "INVALID_CURSOR"
