"""通过运行时热重载加载提示（08-prompt-spec 第 2 节）。

- 业务代码通过键引用提示；当前已发布的
  版本从数据库中解析出来。
- 提供固定键 + 版本查找功能，用于评估重放和调试。
- 带 TTL 的本地缓存；热修改在几秒内生效。
"""

import time
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError, QueryStage
from app.storage.postgres.repositories import PromptTemplateRepository


@dataclass(frozen=True)
class PromptTemplate:
    key: str
    version: int
    content: str
    variables: list[str] = field(default_factory=list)


class PromptLoader:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        ttl_seconds: int = 5,
    ) -> None:
        self._session_factory = session_factory
        self._ttl = ttl_seconds
        self._cache: dict[str, tuple[float, PromptTemplate]] = {}

    async def get(self, key: str, version: int | None = None) -> PromptTemplate:
        if version is None:
            cached = self._cache.get(key)
            if cached and time.monotonic() - cached[0] < self._ttl:
                return cached[1]

        async with self._session_factory() as session:
            repo = PromptTemplateRepository(session)
            row = (
                await repo.get_by_version(key, version)
                if version is not None
                else await repo.get_published(key)
            )

        if row is None:
            raise AppError(
                code="PROMPT_NOT_FOUND",
                message=f"prompt '{key}' (version={version}) not found or not published",
                stage=QueryStage.LLM_GENERATION,
            )

        template = PromptTemplate(
            key=row.key,
            version=row.version,
            content=row.content,
            variables=list(row.variables or []),
        )
        if version is None:
            self._cache[key] = (time.monotonic(), template)
        return template

    def invalidate(self, key: str | None = None) -> None:
        if key is None:
            self._cache.clear()
        else:
            self._cache.pop(key, None)

    @staticmethod
    def render(template: PromptTemplate, variables: dict[str, str]) -> str:
        """Replace {{name}} placeholders. Missing declared variables fail
        loudly; user/retrieval content is always injected as data."""
        content = template.content
        for name in template.variables:
            if name not in variables:
                raise AppError(
                    code="PROMPT_VARIABLE_MISSING",
                    message=f"prompt '{template.key}' v{template.version} requires variable '{name}'",
                    stage=QueryStage.LLM_GENERATION,
                )
            content = content.replace("{{" + name + "}}", variables[name])
        return content
