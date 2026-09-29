"""Redis 入库任务队列（03 节技术选型：Redis 作为任务队列）。

设计：Redis 是"快速通道"，PostgreSQL 仍是任务的唯一事实来源。
- 上传 / 重建后尽力入队；Redis 不可用不影响请求，Worker 周期性扫库兜底。
- Worker 优先 BLPOP 取任务（秒级响应），队列空时执行 DB 扫描
  （重试 backoff、超时回收、孤儿清理）。
- 任务幂等：同一 job 被队列与扫描重复拾取时，处理指纹跳过保证安全
  （04 节 5），因此这里不做去重。
"""

import logging

import redis.asyncio as redis

logger = logging.getLogger(__name__)

QUEUE_KEY = "rag:ingestion:queue"


class IngestionQueue:
    """薄封装：RPUSH 入队 / BLPOP 出队，失败静默降级到 DB 轮询。"""

    def __init__(self, redis_url: str, enabled: bool = True) -> None:
        self._enabled = enabled
        self._client = redis.from_url(redis_url) if enabled else None
        self._broken = False  # 连续失败后停止尝试，等 DB 扫描兜底

    @property
    def usable(self) -> bool:
        """队列是否可用；不可用时 Worker 扫库后需自行休眠，避免空转。"""
        return self._client is not None and not self._broken

    async def enqueue(self, job_id: str) -> None:
        if self._client is None or self._broken:
            return
        try:
            await self._client.rpush(QUEUE_KEY, job_id)
        except Exception as exc:
            # Redis 故障不得阻断上传：任务已在 DB，Worker 扫库会拾取
            logger.warning("redis enqueue failed, falling back to db polling: %s", exc)
            self._broken = True

    async def dequeue(self, timeout: float) -> str | None:
        if self._client is None or self._broken:
            return None
        try:
            item = await self._client.blpop(QUEUE_KEY, timeout=max(1, int(timeout)))
        except Exception as exc:
            logger.warning("redis dequeue failed, falling back to db polling: %s", exc)
            self._broken = True
            return None
        if item is None:
            return None
        _, job_id = item
        return job_id.decode() if isinstance(job_id, bytes) else str(job_id)

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
