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
        except Exception as exc:  # noqa: BLE001 - Redis 故障降级到 DB 兜底，需捕获全部
            # Redis 故障不得阻断上传：任务已在 DB，Worker 扫库会拾取
            logger.warning("redis enqueue failed, falling back to db polling: %s", exc)
            self._broken = True

    async def dequeue(self, timeout: float) -> str | None:
        if self._client is None or self._broken:
            return None
        try:
            item = await self._client.blpop(QUEUE_KEY, timeout=max(1, int(timeout)))
        except Exception as exc:  # noqa: BLE001 - Redis 故障降级到 DB 兜底，需捕获全部
            logger.warning("redis dequeue failed, falling back to db polling: %s", exc)
            self._broken = True
            return None
        if item is None:
            return None
        _, job_id = item
        return job_id.decode() if isinstance(job_id, bytes) else str(job_id)

    async def dequeue_nowait(self) -> str | None:
        """非阻塞取一个任务（LPOP）。

        供 Worker 在拿到首个任务后继续凑批：Redis 快通道若逐个 await 处理，
        单实例实际并发恒为 1，``ingestion_worker_concurrency`` 形同虚设。
        """
        if self._client is None or self._broken:
            return None
        try:
            item = await self._client.lpop(QUEUE_KEY)
        except Exception as exc:  # noqa: BLE001 - Redis 故障降级到 DB 兜底，需捕获全部
            logger.warning("redis lpop failed, falling back to db polling: %s", exc)
            self._broken = True
            return None
        if item is None:
            return None
        return item.decode() if isinstance(item, bytes) else str(item)

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()


EVENT_QUEUE_KEY = "rag:events:queue"


class EventQueue:
    """入站事件队列（12-agent-platform-spec §2.1 接入层）。

    与 IngestionQueue 同模式、独立 key；事件以 JSON 字符串入队，消费端
    （触发对应 Job / Agent）作为后续接入。

    容量语义：``maxlen`` 是**硬上限**，满了直接拒收（``enqueue`` 返回
    False，路由转 503）。不用 LTRIM 丢弃最旧事件——那会在调用方拿到 202
    「已受理」的同时把事件悄悄扔掉，与路由声明的「宁可拒收也不丢事件」
    相矛盾。无消费端时运营者会持续看到 503，这是可见的、可修的信号。
    """

    def __init__(self, redis_url: str, enabled: bool = True, maxlen: int = 10000) -> None:
        self._enabled = enabled
        self._client = redis.from_url(redis_url) if enabled else None
        self._broken = False
        self._maxlen = maxlen

    @property
    def usable(self) -> bool:
        return self._client is not None and not self._broken

    async def enqueue(self, payload: str) -> bool:
        """入队并返回是否受理；容量满或 Redis 不可用返回 False。"""
        if self._client is None or self._broken:
            return False
        try:
            if self._maxlen and self._maxlen > 0:
                size = await self._client.llen(EVENT_QUEUE_KEY)
                if size >= self._maxlen:
                    # 不丢旧事件：宁可让调用方拿到 503 去重试/告警。
                    logger.error(
                        "event queue full (%s/%s); event rejected", size, self._maxlen
                    )
                    return False
            await self._client.rpush(EVENT_QUEUE_KEY, payload)
            return True
        except Exception as exc:  # noqa: BLE001 - Redis 故障降级到 DB 兜底，需捕获全部
            logger.warning("redis event enqueue failed: %s", exc)
            self._broken = True
            return False

    async def dequeue(self, timeout: float) -> str | None:
        if self._client is None or self._broken:
            return None
        try:
            item = await self._client.blpop(EVENT_QUEUE_KEY, timeout=max(1, int(timeout)))
        except Exception as exc:  # noqa: BLE001 - Redis 故障降级到 DB 兜底，需捕获全部
            logger.warning("redis event dequeue failed: %s", exc)
            self._broken = True
            return None
        if item is None:
            return None
        _, payload = item
        return payload.decode() if isinstance(payload, bytes) else str(payload)

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
