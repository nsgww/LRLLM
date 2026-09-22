"""UUID parsing contract (05-api-spec section 4: bad params -> 400)."""

import uuid

import pytest

from app.core.errors import AppError
from app.core.ids import parse_uuid


def test_valid_uuid_string_is_parsed():
    value = uuid.uuid4()
    assert parse_uuid(str(value)) == value


def test_uuid_object_passes_through():
    value = uuid.uuid4()
    assert parse_uuid(value) is value


def test_invalid_uuid_raises_classified_400():
    with pytest.raises(AppError) as exc_info:
        parse_uuid("not-a-uuid", "knowledge_base_id")
    assert exc_info.value.http_status == 400
    assert exc_info.value.code == "INVALID_ID"
    assert "knowledge_base_id" in exc_info.value.message
