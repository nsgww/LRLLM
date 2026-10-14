"""共享依赖项（05-api-spec 第 3 节）。

v0.1 是一个单一的共享知识空间：无租户隔离。
知识库范围仅由 X-Knowledge-Base-ID 头字段决定；
正文中声明范围的字段将被忽略。

安全（可选）：设置 RAG_API_KEY 后，所有 /v1 请求都要求
`Authorization: Bearer <key>`。不设置时鉴权关闭，保持单机开发体验。
用 `secrets.compare_digest` 做恒定时间比较，避免时序侧信道。
"""

import secrets

from fastapi import Header

from app.core.config import get_settings
from app.core.errors import AppError
from app.policy.models import Subject


def require_kb_id(x_knowledge_base_id: str | None = Header(default=None)) -> str:
    if not x_knowledge_base_id:
        raise AppError(
            code="KB_HEADER_MISSING",
            message="X-Knowledge-Base-ID header is required",
            http_status=400,
        )
    return x_knowledge_base_id


def require_api_key(authorization: str | None = Header(default=None)) -> None:
    """API Key 鉴权。未配置 RAG_API_KEY 时为 no-op（向后兼容）。"""
    expected = get_settings().api_key
    if not expected:
        return

    provided = ""
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer":
            provided = token.strip()

    # 恒定时间比较，避免按位试探
    if not provided or not secrets.compare_digest(provided, expected):
        raise AppError(
            code="UNAUTHORIZED",
            message="missing or invalid credentials",
            http_status=401,
        )


def require_subject(
    x_subject_id: str | None = Header(default=None),
    x_subject_roles: str | None = Header(default=None),
) -> Subject:
    """解析身份主体（12 §2.4）。缺省 anonymous/user；生产可由 API Key 映射覆盖。"""
    subject_id = (x_subject_id or "").strip() or "anonymous"
    roles = tuple(
        r.strip() for r in (x_subject_roles or "user").split(",") if r.strip()
    )
    return Subject(id=subject_id, roles=roles or ("user",))
