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
