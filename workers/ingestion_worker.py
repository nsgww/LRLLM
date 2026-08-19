"""Poll-based ingestion worker (04-ingestion-pipeline-spec section 3).

Upload/Sync only create jobs; this worker executes the pipeline.
v0.1 assumes a single worker instance (no job-claiming race handling).

Run: python -m workers.ingestion_worker
"""

import asyncio
import logging

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.embedding.providers.openai import OpenAIEmbedding
from app.ingestion.pipeline import IngestionPipeline
from app.storage.postgres.db import get_session_factory, init_engine
from app.storage.postgres.repositories import IngestionJobRepository
from app.storage.qdrant.store import QdrantVectorStore

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 2.0


async def run() -> None:
    settings = get_settings()
    setup_logging()
    init_engine(settings.postgres_dsn)
    session_factory = get_session_factory()

    vector_store = QdrantVectorStore(
        settings.qdrant_url,
        settings.qdrant_collection,
        settings.embedding_dimension,
    )
    await vector_store.ensure_collection()
    await vector_store.validate_dimension()

    embedding = OpenAIEmbedding(
        model=settings.embedding_model,
        model_version=settings.embedding_model_version,
        dimension=settings.embedding_dimension,
        api_key=settings.embedding_api_key,
        base_url=settings.embedding_base_url,
    )
    pipeline = IngestionPipeline(
        session_factory=session_factory,
        vector_store=vector_store,
        embedding=embedding,
        settings=settings,
    )

    logger.info("ingestion worker started")
    while True:
        async with session_factory() as session:
            jobs = await IngestionJobRepository(session).list_pending()
        for job in jobs:
            try:
                result = await pipeline.process(str(job.id))
                logger.info(
                    "job %s -> %s (sections=%s chunks=%s embeddings=%s skipped=%s)",
                    result.job_id,
                    result.status.value,
                    result.section_count,
                    result.chunk_count,
                    result.embedding_count,
                    result.skipped,
                )
            except Exception:
                logger.exception("job %s failed", job.id)
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(run())
