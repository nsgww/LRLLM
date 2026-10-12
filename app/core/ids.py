"""UUID parsing with a classified 400 error instead of a bare ValueError.

External identifiers (path params, X-Knowledge-Base-ID, body ids) reach the
repositories as strings. Parsing them must yield a 400 Client Error
(05-api-spec section 4), never an unhandled 500.
"""

import uuid

from app.core.errors import AppError


def parse_uuid(value: str, field: str = "id") -> uuid.UUID:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise AppError(
            code="INVALID_ID",
            message=f"{field} is not a valid UUID: {value!r}",
            http_status=400,
        ) from exc


def assert_same_kb(row, kb_id: str) -> None:
    """Raise 404 unless ``row`` belongs to ``kb_id`` (IDOR / cross-KB guard).

    Returns 404 rather than 403 so the existence of another knowledge base's
    resource is never confirmed. Compares the row's ``knowledge_base_id`` (a
    ``uuid.UUID``) against the parsed ``X-Knowledge-Base-ID`` header.
    """
    row_kb = getattr(row, "knowledge_base_id", None)
    if row is None or row_kb is None or row_kb != parse_uuid(kb_id, "X-Knowledge-Base-ID"):
        raise AppError(
            code="NOT_FOUND",
            message="resource not found in this knowledge base",
            http_status=404,
        )
