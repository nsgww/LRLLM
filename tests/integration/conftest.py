"""Integration test fixtures.

These tests exercise the real storage contracts (10 section 7). They need a
live PostgreSQL with the schema from ``scripts/init_db.sql`` and a live Qdrant.
When those are unavailable the whole module is skipped rather than failing, so
``pytest`` stays green on a laptop without infrastructure.
"""

import os

import pytest
import pytest_asyncio

from app.core.config import Settings
from app.storage.postgres.db import dispose_engine, get_session_factory, init_engine


def _postgres_reachable(dsn: str) -> bool:
    import asyncio

    import sqlalchemy as sa

    async def probe() -> bool:
        engine = None
        try:
            from sqlalchemy.ext.asyncio import create_async_engine

            engine = create_async_engine(dsn, pool_pre_ping=True)
            async with engine.connect() as conn:
                await conn.execute(sa.text("SELECT 1"))
            return True
        except Exception:  # noqa: BLE001 - probe: any failure means unreachable
            return False
        finally:
            if engine is not None:
                await engine.dispose()

    return asyncio.run(probe())


@pytest.fixture(scope="session")
def integration_settings() -> Settings:
    return Settings()


@pytest.fixture(scope="session", autouse=True)
def _require_infrastructure(integration_settings: Settings):
    if os.environ.get("RAG_SKIP_INTEGRATION"):
        pytest.skip("RAG_SKIP_INTEGRATION set")
    if not _postgres_reachable(integration_settings.postgres_dsn):
        pytest.skip("PostgreSQL not reachable; skipping integration tests")


@pytest_asyncio.fixture
async def session_factory(integration_settings: Settings):
    init_engine(integration_settings.postgres_dsn)
    factory = get_session_factory()
    try:
        yield factory
    finally:
        await dispose_engine()


@pytest_asyncio.fixture
async def clean_kb(session_factory):
    """Create a throwaway knowledge base and cascade-delete it afterwards."""
    import uuid

    import sqlalchemy as sa

    from app.storage.postgres.orm import (
        ChunkRow,
        DocumentRow,
        KnowledgeBaseRow,
        SectionRow,
    )

    kb_id = str(uuid.uuid4())
    async with session_factory() as session:
        session.add(KnowledgeBaseRow(id=uuid.UUID(kb_id), name=f"it-{kb_id[:8]}"))
        await session.commit()
    try:
        yield kb_id
    finally:
        async with session_factory() as session:
            doc_ids = sa.select(DocumentRow.id).where(DocumentRow.knowledge_base_id == uuid.UUID(kb_id))
            await session.execute(sa.delete(ChunkRow).where(ChunkRow.knowledge_base_id == uuid.UUID(kb_id)))
            await session.execute(sa.delete(SectionRow).where(SectionRow.document_id.in_(doc_ids)))
            await session.execute(sa.delete(DocumentRow).where(DocumentRow.knowledge_base_id == uuid.UUID(kb_id)))
            await session.execute(sa.delete(KnowledgeBaseRow).where(KnowledgeBaseRow.id == uuid.UUID(kb_id)))
            await session.commit()
