"""EventQueue 测试（12-agent-platform-spec §2.1 接入层）。"""

import asyncio

from app.services.queue import EventQueue, IngestionQueue


class _FakeRedis:
    def __init__(self):
        self.q: list = []
        self.closed = False

    async def rpush(self, key, val):
        self.q.append(val)
        return len(self.q)

    async def llen(self, key):
        return len(self.q)

    async def lpop(self, key):
        if not self.q:
            return None
        value = self.q.pop(0)
        return value.encode() if isinstance(value, str) else value

    async def blpop(self, key, timeout):
        if self.q:
            v = self.q.pop(0)
            return (key, v.encode() if isinstance(v, str) else v)
        return None

    async def aclose(self):
        self.closed = True


def test_event_queue_roundtrip(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr("app.services.queue.redis.from_url", lambda url: fake)
    q = EventQueue("redis://x")
    asyncio.run(q.enqueue('{"event_id":"e1","type":"doc.uploaded"}'))
    out = asyncio.run(q.dequeue(1))
    assert out == '{"event_id":"e1","type":"doc.uploaded"}'
    asyncio.run(q.aclose())
    assert fake.closed is True


def test_event_queue_rejects_when_full_instead_of_dropping(monkeypatch):
    """满队列必须拒收（调用方转 503），不能丢最旧事件。

    否则调用方拿到 202「已受理」而事件被静默丢弃，与接入层声明的
    「宁可拒收也不丢事件」相矛盾。
    """
    fake = _FakeRedis()
    monkeypatch.setattr("app.services.queue.redis.from_url", lambda url: fake)
    q = EventQueue("redis://x", maxlen=2)

    assert asyncio.run(q.enqueue("e1")) is True
    assert asyncio.run(q.enqueue("e2")) is True
    assert asyncio.run(q.enqueue("e3")) is False  # 满了：拒收

    # 旧事件必须完整保留
    assert fake.q == ["e1", "e2"]


def test_ingestion_queue_dequeue_nowait_is_non_blocking(monkeypatch):
    """快通道凑批依赖 LPOP：队列空时立刻返回 None，而不是阻塞等 BLPOP 超时。"""
    fake = _FakeRedis()

    async def lpop(key):
        if fake.q:
            value = fake.q.pop(0)
            return value.encode() if isinstance(value, str) else value
        return None

    fake.lpop = lpop
    monkeypatch.setattr("app.services.queue.redis.from_url", lambda url: fake)

    queue = IngestionQueue("redis://x")
    asyncio.run(queue.enqueue("job-1"))
    asyncio.run(queue.enqueue("job-2"))

    assert asyncio.run(queue.dequeue_nowait()) == "job-1"
    assert asyncio.run(queue.dequeue_nowait()) == "job-2"
    assert asyncio.run(queue.dequeue_nowait()) is None
    asyncio.run(queue.aclose())


def test_ingestion_queue_nowait_broken_returns_none(monkeypatch):
    """Redis 故障后不再尝试，交由 DB 扫库兜底。"""
    fake = _FakeRedis()

    async def lpop(key):
        raise RuntimeError("redis down")

    fake.lpop = lpop
    monkeypatch.setattr("app.services.queue.redis.from_url", lambda url: fake)

    queue = IngestionQueue("redis://x")
    assert asyncio.run(queue.dequeue_nowait()) is None
    assert queue.usable is False  # 标记故障后不再重试
