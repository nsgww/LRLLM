"""共享依赖项（05-api-spec 第 3 节）。

v0.1 是一个单一的共享知识空间：无需身份验证，无租户。
知识库范围仅由 X-Knowledge-Base-ID 头字段决定；
正文中声明范围的字段将被忽略。
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
