"""Import prompt seed templates into prompt_templates (10 section 6).

Each seed file becomes version 1 PUBLISHED when no PUBLISHED version
exists for its key. Existing published prompts are never overwritten;
runtime changes go through new versions (08 section 2).

Run: python -m scripts.seed_prompts
"""

import asyncio
import re
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.storage.postgres.db import get_session_factory, init_engine
from app.storage.postgres.repositories import PromptTemplateRepository

SEED_DIR = Path(__file__).resolve().parent.parent / "app" / "llm" / "prompts" / "seed"
_VAR_RE = re.compile(r"{{(\w+)}}")


async def main() -> None:
    settings = get_settings()
    setup_logging()
    init_engine(settings.postgres_dsn)
    session_factory = get_session_factory()

    async with session_factory() as session:
        repo = PromptTemplateRepository(session)
        for path in sorted(SEED_DIR.glob("*.md")):
            key = path.stem
            content = path.read_text(encoding="utf-8")
            variables = sorted(set(_VAR_RE.findall(content)))
            if await repo.get_published(key) is not None:
                print(f"skip {key}: already published")
                continue
            row = await repo.create_version(
                key=key,
                content=content,
                variables=variables,
                status="PUBLISHED",
                created_by="seed",
            )
            print(f"seeded {key} v{row.version} (variables: {variables})")
        await session.commit()


if __name__ == "__main__":
    asyncio.run(main())
