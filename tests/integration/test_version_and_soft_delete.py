"""Version filter and soft-delete semantics (02 sections 9/22, 10 section 7).

- A specified version must be an exact storage-layer match: zero cross-version
  recall (06 section 14 #2).
- Soft delete must make a document immediately unretrievable (09 section 11).
"""

import uuid

import pytest

from app.domain.chunk import ChunkType
from app.domain.document import DocumentStatus
from app.domain.retrieval import MetadataFilter
from app.storage.keyword.store import PostgresKeywordStore
from app.storage.postgres.orm import ChunkRow, DocumentRow, KnowledgeBaseRow

pytestmark = pytest.mark.asyncio


async def _seed(session_factory, kb_id, text, version, *, deleted: bool = False):
    from datetime import UTC, datetime

    async with session_factory() as session:
        doc = DocumentRow(
            knowledge_base_id=uuid.UUID(kb_id),
            title=f"doc-{version}",
            content=text.encode("utf-8"),
            content_hash=uuid.uuid4().hex,
            product="MCP",
            version=version,
            status=DocumentStatus.READY,
            deleted_at=datetime.now(UTC) if deleted else None,
        )
        session.add(doc)
        await session.flush()
        session.add(
            ChunkRow(
                knowledge_base_id=uuid.UUID(kb_id),
                document_id=doc.id,
                text=text,
                heading_path="MCP / Guide",
                line_start=1,
                line_end=2,
                chunk_type=ChunkType.TEXT,
                chunk_index=0,
                token_count=3,
                content_hash=uuid.uuid4().hex,
                product="MCP",
                version=version,
                deleted_at=datetime.now(UTC) if deleted else None,
            )
        )
        await session.commit()


@pytest.fixture
async def kb(session_factory):
    import sqlalchemy as sa

    kb_id = str(uuid.uuid4())
    async with session_factory() as session:
        session.add(KnowledgeBaseRow(id=uuid.UUID(kb_id), name=f"it-ver-{kb_id[:8]}"))
        await session.commit()
    try:
        yield kb_id
    finally:
        async with session_factory() as session:
            await session.execute(sa.delete(ChunkRow).where(ChunkRow.knowledge_base_id == uuid.UUID(kb_id)))
            await session.execute(sa.delete(DocumentRow).where(DocumentRow.knowledge_base_id == uuid.UUID(kb_id)))
            await session.execute(sa.delete(KnowledgeBaseRow).where(KnowledgeBaseRow.id == uuid.UUID(kb_id)))
            await session.commit()


async def test_specified_version_is_exact_match(session_factory, kb):
    await _seed(session_factory, kb, "version fifty three oauth guide", "0.5.3")
    await _seed(session_factory, kb, "version sixty oauth guide", "0.6.0")

    store = PostgresKeywordStore(session_factory)
    hits = await store.search(
        "oauth guide", MetadataFilter(knowledge_base_id=kb, product="MCP", version="0.5.3"), top_k=50
    )
    assert hits, "expected the matching version to be recalled"
    assert all(h.payload.get("version") == "0.5.3" for h in hits), "cross-version leak"


async def test_unspecified_version_allows_multiple(session_factory, kb):
    await _seed(session_factory, kb, "shared oauth guide alpha", "0.5.3")
    await _seed(session_factory, kb, "shared oauth guide beta", "0.6.0")

    store = PostgresKeywordStore(session_factory)
    hits = await store.search(
        "oauth guide", MetadataFilter(knowledge_base_id=kb, product="MCP"), top_k=50
    )
    versions = {h.payload.get("version") for h in hits}
    assert {"0.5.3", "0.6.0"} <= versions, "both versions should be eligible"


async def test_soft_deleted_document_is_not_retrievable(session_factory, kb):
    await _seed(session_factory, kb, "deleted sentinel content", "0.5.3", deleted=True)

    store = PostgresKeywordStore(session_factory)
    hits = await store.search(
        "sentinel", MetadataFilter(knowledge_base_id=kb, product="MCP"), top_k=50
    )
    assert hits == [], "soft-deleted chunk must be immediately excluded"
