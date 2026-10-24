"""入库 Worker（04-ingestion-pipeline-spec 第 3 节）。

上传/重建只创建任务，由本 Worker 执行管线。

取任务的方式：优先 BLPOP Redis 队列（秒级响应）；队列空或 Redis
不可用时回退到周期扫库（退避重试、超时回收、孤儿清理），
PostgreSQL 始终是任务的唯一事实来源。

韧性（04 节 34 / 09 节 11）：
- Worker 崩溃遗留的 RUNNING 任务会被回收重试；
- 瞬时失败按退避重排，最多 `ingestion_max_attempts` 次。

Concurrency: ``claim_pending`` uses ``FOR UPDATE SKIP LOCKED`` so multiple
worker replicas co-exist without processing the same job twice.

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


async def claim_due_jobs(
    session_factory: async_sessionmaker[AsyncSession],
    limit: int,
) -> list[str]:
    """Claim due PENDING jobs atomically and return their ids.

    ``claim_pending`` flips the rows to RUNNING in the same statement, so the
    commit below both persists the claim and releases the row locks; other
    workers then see these jobs as RUNNING and skip them.
    """
    async with session_factory() as session:
        job_ids = await IngestionJobRepository(session).claim_pending(limit)
        await session.commit()
        return job_ids


async def run() -> None:
    settings = get_settings()
    setup_logging()
    # 出站地址安全校验与 API 进程一致：worker 会带着 embedding_api_key 访问
    # base_url，私网/云元数据地址必须显式放行，否则拒绝启动（防 SSRF + 密钥外泄）。
    host_issues = settings.outbound_host_issues()
    if host_issues:
        raise RuntimeError(
            "unsafe outbound base_url configuration:\n  - " + "\n  - ".join(host_issues)
        )
    init_engine(
        settings.postgres_dsn,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_recycle=settings.db_pool_recycle,
    )
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
        timeout=settings.embedding_timeout_seconds,
        max_attempts=settings.provider_max_attempts,
        retry_backoff=settings.provider_retry_backoff_seconds,
    )
    pipeline = IngestionPipeline(
        session_factory=session_factory,
        vector_store=vector_store,
        embedding=embedding,
        settings=settings,
    )
    cleanup = CleanupService(
        session_factory,
        vector_store,
        settings.cleanup_batch_size,
        trace_retention_days=settings.trace_retention_days,
        audit_retention_days=settings.audit_retention_days,
    )
    queue = IngestionQueue(settings.redis_url, settings.redis_queue_enabled)
    concurrency = max(1, settings.ingestion_worker_concurrency)

    logger.info("ingestion worker started (concurrency=%s)", concurrency)
    try:
        try:
            await cleanup.reconcile_orphans()
        except Exception:
            # 对账失败（如旧库尚未加 ON DELETE CASCADE）不能阻止 worker 启动
            logger.exception("startup orphan reconciliation failed; continuing")
        while True:
            # 快速通道：队列有任务就连续消费，没有则等一个轮询周期
            job_id = await queue.dequeue(settings.ingestion_poll_interval_seconds)
            if job_id is not None:
                # 凑批后并发处理：逐个 await 会让 Redis 路径的实际并发恒为 1，
                # ``ingestion_worker_concurrency`` 只在 DB 兜底分支生效。
                batch = [job_id]
                while len(batch) < concurrency:
                    extra = await queue.dequeue_nowait()
                    if extra is None:
                        break
                    batch.append(extra)
                await asyncio.gather(*(process_job(pipeline, jid) for jid in batch))
                continue
            # 队列空（或 Redis 不可用）：周期扫库兜底
            try:
                await reclaim_stale_jobs(session_factory, settings)
                report = await cleanup.run_once()
                if (
                    report.chunks_purged
                    or report.documents_purged
                    or report.traces_purged
                    or report.audit_logs_purged
                ):
                    logger.info(
                        "cleanup purged chunks=%s documents=%s traces=%s audit=%s",
                        report.chunks_purged,
                        report.documents_purged,
                        report.traces_purged,
                        report.audit_logs_purged,
                    )
            except Exception:
                # 维护任务是尽力而为：单轮失败只记录，绝不能让 worker 进程退出
                logger.exception("maintenance pass failed; will retry next cycle")
            # DB 兜底：原子抢占一批到期任务（FOR UPDATE SKIP LOCKED），
            # 并发处理以压榨外部 API 的等待时间。
            job_ids = await claim_due_jobs(session_factory, limit=concurrency)
            if job_ids:
                await asyncio.gather(*(process_job(pipeline, job_id) for job_id in job_ids))
            # 队列可用时 dequeue 已阻塞等待一个周期；不可用时需自行休眠防空转
            if not queue.usable:
                await asyncio.sleep(settings.ingestion_poll_interval_seconds)
    finally:
        await queue.aclose()
        await embedding.aclose()
        await vector_store.aclose()


async def process_job(pipeline: IngestionPipeline, job_id: str) -> None:
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


if __name__ == "__main__":
    asyncio.run(run())
