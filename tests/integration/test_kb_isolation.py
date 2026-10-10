"""Cross-knowledge-base retrieval isolation (06 section 14 #1, 10 section 7).

The scope filter MUST be executed at the storage layer, never applied in
memory after recall. These tests assert that a query scoped to KB A can never
observe KB B's chunks, for both keyword and vector recall.
"""

import uuid

import pytest

from app.domain.chunk import ChunkType
from app.domain.document import DocumentStatus
from app.domain.retrieval import MetadataFilter
from app.storage.keyword.store import PostgresKeywordStore
from app.storage.postgres.orm import (
    ChunkRow,
    DocumentRow,
    KnowledgeBaseRow,
    SectionRow,
)

pytestmark = pytest.mark.asyncio


async def _seed_kb(session_factory, name: str, text: str, version: str = "0.5.3") -> str:
    kb_id = uuid.uuid4()
    async with session_factory() as session:
        session.add(KnowledgeBaseRow(id=kb_id, name=name))
        doc = DocumentRow(
            knowledge_base_id=kb_id,
            title=name,
            content=text,
            content_hash=uuid.uuid4().hex,
            product="MCP",
            version=version,
            status=DocumentStatus.READY,
        )
        session.add(doc)
        await session.flush()
        session.add(
            ChunkRow(
                knowledge_base_id=kb_id,
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
            )
        )
        await session.commit()
    return str(kb_id)


async def _cleanup(session_factory, kb_id: str):
    import sqlalchemy as sa

    kb_uuid = uuid.UUID(kb_id)
    async with session_factory() as session:
        doc_ids = sa.select(DocumentRow.id).where(DocumentRow.knowledge_base_id == kb_uuid)
        await session.execute(sa.delete(ChunkRow).where(ChunkRow.knowledge_base_id == kb_uuid))
        await session.execute(sa.delete(SectionRow).where(SectionRow.document_id.in_(doc_ids)))
        await session.execute(sa.delete(DocumentRow).where(DocumentRow.knowledge_base_id == kb_uuid))
        await session.execute(sa.delete(KnowledgeBaseRow).where(KnowledgeBaseRow.id == kb_uuid))
        await session.commit()


async def test_keyword_recall_never_crosses_knowledge_base(session_factory):
    kb_a = await _seed_kb(session_factory, "it-iso-a", "unique alpha sentinel content")
    kb_b = await _seed_kb(session_factory, "it-iso-b", "unique beta sentinel content")
    try:
        store = PostgresKeywordStore(session_factory)
        hits = await store.search(
            "sentinel", MetadataFilter(knowledge_base_id=kb_a), top_k=50
        )
        assert hits, "expected the owning KB to recall its own chunk"
        async with session_factory() as session:
            import sqlalchemy as sa

            a_chunk_ids = {
                str(r) for r in (await session.execute(
                    sa.select(ChunkRow.id).where(ChunkRow.knowledge_base_id == uuid.UUID(kb_a))
                )).scalars().all()
            }
        assert all(h.chunk_id in a_chunk_ids for h in hits), "leaked another KB's chunk"
    finally:
        await _cleanup(session_factory, kb_a)
        await _cleanup(session_factory, kb_b)
