"""EventQueue 测试（12-agent-platform-spec §2.1 接入层）。"""

import asyncio

from app.services.queue import EventQueue


class _FakeRedis:
    def __init__(self):
        self.q: list = []
        self.closed = False

    async def rpush(self, key, val):
        self.q.append(val)
        return len(self.q)

    async def ltrim(self, key, start, end):
        # 与 Redis 语义一致：保留 [start, end] 区间（负索引从尾部计数）。
        self.q = self.q[start:] if end == -1 else self.q
        return True

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
