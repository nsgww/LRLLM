"""Shared dependencies (05-api-spec section 3).

v0.1 is a single shared knowledge space: no authentication, no tenants.
The knowledge base scope comes from the X-Knowledge-Base-ID header only;
body fields claiming a scope are ignored.
"""

from fastapi import Header

from app.core.errors import AppError


def require_kb_id(x_knowledge_base_id: str | None = Header(default=None)) -> str:
    if not x_knowledge_base_id:
        raise AppError(
            code="KB_HEADER_MISSING",
            message="X-Knowledge-Base-ID header is required",
            http_status=400,
        )
    return x_knowledge_base_id
