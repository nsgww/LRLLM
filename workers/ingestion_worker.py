"""入库 Worker（04-ingestion-pipeline-spec 第 3 节）。

上传/重建只创建任务，由本 Worker 执行管线。
v0.1 假定单 Worker 实例（不做任务抢占竞争处理）。

取任务的方式：优先 BLPOP Redis 队列（秒级响应）；队列空或 Redis
不可用时回退到周期扫库（退避重试、超时回收、孤儿清理），
PostgreSQL 始终是任务的唯一事实来源。

韧性（04 节 34 / 09 节 11）：
- Worker 崩溃遗留的 RUNNING 任务会被回收重试；
- 瞬时失败按退避重排，最多 `ingestion_max_attempts` 次。

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
from app.services.queue import IngestionQueue
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


async def _process_job(pipeline: IngestionPipeline, job_id: str) -> None:
    """执行单个任务；管线内部幂等，队列与扫库重复拾取是安全的。"""
    try:
        result = await pipeline.process(job_id)
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
        logger.exception("job %s failed", job_id)


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
    queue = IngestionQueue(settings.redis_url, settings.redis_queue_enabled)

    logger.info("ingestion worker started")
    try:
        await cleanup.reconcile_orphans()
        while True:
            # 快速通道：队列有任务就连续消费，没有则等一个轮询周期
            job_id = await queue.dequeue(settings.ingestion_poll_interval_seconds)
            if job_id is not None:
                await _process_job(pipeline, job_id)
                continue
            # 队列空（或 Redis 不可用）：周期扫库兜底
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
                await _process_job(pipeline, str(job.id))
            # 队列可用时 dequeue 已阻塞等待一个周期；不可用需自行休眠防空转
            if not queue.usable:
                await asyncio.sleep(settings.ingestion_poll_interval_seconds)
    finally:
        await queue.aclose()
        await embedding.aclose()
        await vector_store.aclose()


if __name__ == "__main__":
    asyncio.run(run())
