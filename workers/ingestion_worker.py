"""Poll-based ingestion worker (04-ingestion-pipeline-spec section 3).

Upload/Sync only create jobs; this worker executes the pipeline.
v0.1 assumes a single worker instance (no job-claiming race handling).

Resilience (04 section 34 / 09 section 11):
- RUNNING jobs left behind by a crashed worker are reclaimed and retried;
- transient failures are requeued with backoff up to `ingestion_max_attempts`.

Run: python -m workers.ingestion_worker
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.logging import setup_logging
from app.core.startup import validate_embedding_consistency
from app.domain.ingestion import JobStatus
from app.embedding.providers.openai import OpenAIEmbedding
from app.ingestion.pipeline import IngestionPipeline
from app.services.cleanup_service import CleanupService
from app.storage.postgres.db import get_session_factory, init_engine
from app.storage.postgres.repositories import IngestionJobRepository
from app.storage.qdrant.store import QdrantVectorStore

logger = logging.getLogger(__name__)


async def reclaim_stale_jobs(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    """Recover jobs stuck in RUNNING (worker crashed mid-processing)."""
    cutoff = datetime.now(UTC) - timedelta(seconds=settings.ingestion_stale_job_timeout_seconds)
    async with session_factory() as session:
        jobs = IngestionJobRepository(session)
        stale = await jobs.list_stale_running(cutoff)
        for job in stale:
            attempts = job.attempt_count or 0
            if attempts < settings.ingestion_max_attempts:
                backoff = settings.ingestion_retry_backoff_seconds * max(attempts, 1)
                await jobs.requeue(
                    str(job.id), datetime.now(UTC) + timedelta(seconds=backoff)
                )
                logger.warning(
                    "reclaimed stale job %s (attempt %s/%s), retrying after %ss",
                    job.id,
                    attempts,
                    settings.ingestion_max_attempts,
                    backoff,
                )
            else:
                await jobs.update(
                    str(job.id),
                    JobStatus.FAILED,
                    stage="TIMEOUT",
                    error_code="JOB_TIMEOUT",
                    error_message="job stayed RUNNING beyond the stale timeout",
                )
                logger.error("job %s exhausted attempts after worker crash", job.id)
        if stale:
            await session.commit()


async def run() -> None:
    settings = get_settings()
    setup_logging()
    init_engine(settings.postgres_dsn)
    session_factory = get_session_factory()
    await validate_embedding_consistency(session_factory, settings)

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
    cleanup = CleanupService(session_factory, vector_store, settings.cleanup_batch_size)

    logger.info("ingestion worker started")
    try:
        await cleanup.reconcile_orphans()
        while True:
            await reclaim_stale_jobs(session_factory, settings)
            report = await cleanup.run_once()
            if report.chunks_purged or report.documents_purged:
                logger.info(
                    "cleanup purged chunks=%s documents=%s",
                    report.chunks_purged,
                    report.documents_purged,
                )
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
            await asyncio.sleep(settings.ingestion_poll_interval_seconds)
    finally:
        await embedding.aclose()
        await vector_store.aclose()


if __name__ == "__main__":
    asyncio.run(run())
