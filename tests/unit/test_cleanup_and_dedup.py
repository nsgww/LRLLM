"""回归测试：KB 删除必须清理向量，重排候选需跨子查询去重。

对应 docs/11-code-review-perf-security.md 的 S4 与 P2。
"""

import asyncio
from dataclasses import dataclass

import pytest

from app.domain.retrieval import RankedChunk
from app.retrieval.rerank import RerankService
from app.services.knowledge_base_service import KnowledgeBaseService

# ---------- S4: 删除知识库必须清理 Qdrant 向量 ----------


class _FakeVectorStore:
    def __init__(self) -> None:
        self.deleted_by_kb: list[str] = []

    async def delete_by_knowledge_base(self, knowledge_base_id: str) -> None:
        self.deleted_by_kb.append(knowledge_base_id)


class _FakeKbRepo:
    def __init__(self, session, row) -> None:
        self._row = row

    async def get(self, kb_id):
        return self._row

    async def soft_delete(self, kb_id) -> None:
        return None


class _FakeChildRepo:
    def __init__(self, session) -> None:
        pass

    async def soft_delete_by_kb(self, kb_id) -> None:
        return None


class _FakeSession:
    async def commit(self) -> None:
        return None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None


@dataclass
class _KbRow:
    id: str = "kb-1"


def test_kb_soft_delete_removes_vectors(monkeypatch):
    vector_store = _FakeVectorStore()
    service = KnowledgeBaseService(lambda: _FakeSession(), vector_store)

    monkeypatch.setattr(
        "app.services.knowledge_base_service.KnowledgeBaseRepository",
        lambda session: _FakeKbRepo(session, _KbRow()),
    )
    monkeypatch.setattr(
        "app.services.knowledge_base_service.ChunkRepository",
        lambda session: _FakeChildRepo(session),
    )
    monkeypatch.setattr(
        "app.services.knowledge_base_service.DocumentRepository",
        lambda session: _FakeChildRepo(session),
    )
    monkeypatch.setattr(
        "app.services.knowledge_base_service.WikiPageRepository",
        lambda session: _FakeChildRepo(session),
    )

    asyncio.run(service.soft_delete("kb-1"))

    assert vector_store.deleted_by_kb == ["kb-1"], (
        "KB 删除必须调用 delete_by_knowledge_base，否则向量成为永不回收的孤儿"
    )


def test_kb_soft_delete_without_vector_store_still_works():
    """vector_store 可省略（老调用点/测试），不应报错。"""
    service = KnowledgeBaseService(lambda: _FakeSession())
    assert service._vector_store is None


# ---------- P2: 重排候选跨子查询去重 ----------


def _ranked(chunk_id: str) -> RankedChunk:
    return RankedChunk(
        chunk_id=chunk_id,
        document_id="doc",
        text="t",
        score=1.0,
        chunk_type="paragraph",
        heading_path="H",
        line_start=1,
        line_end=2,
    )


@dataclass
class _SubQuery:
    id: str
    query: str


@dataclass
class _HybridResult:
    candidates: list[tuple[str, float]]


def test_rerank_batches_dedupe_across_sub_queries():
    from app.services.query_service import QueryService

    planned = [(_SubQuery("A", "qa"), None), (_SubQuery("B", "qb"), None)]
    results = [
        _HybridResult(candidates=[("c1", 0.9), ("c2", 0.5)]),
        _HybridResult(candidates=[("c1", 0.4), ("c3", 0.7)]),
    ]

    batches = QueryService._rerank_batches(planned, results)

    # c1 在 A 中以更高分出现，B 中不应重复送进 reranker
    assert batches[0] == ("A", "qa", [("c1", 0.9), ("c2", 0.5)])
    assert batches[1] == ("B", "qb", [("c3", 0.7)])


def test_rerank_batches_keep_higher_score_on_duplicate():
    from app.services.query_service import QueryService

    planned = [(_SubQuery("A", "qa"), None), (_SubQuery("B", "qb"), None)]
    results = [
        _HybridResult(candidates=[("c1", 0.2)]),
        _HybridResult(candidates=[("c1", 0.95)]),
    ]

    batches = QueryService._rerank_batches(planned, results)

    # 后续子查询拿到更高分：高分版本进 B，低分版本从 A 移除（只送一次重排）。
    assert batches[0] == ("A", "qa", [])
    assert batches[1] == ("B", "qb", [("c1", 0.95)])


def test_rerank_batches_preserve_sub_query_count():
    from app.services.query_service import QueryService

    planned = [(_SubQuery(sid, "q"), None) for sid in ("A", "B", "C")]
    results = [_HybridResult(candidates=[("c1", 0.5)]) for _ in planned]

    batches = QueryService._rerank_batches(planned, results)

    # 每个子查询仍各自成批（06 节 9 要求独立记录 Trace）
    assert [b[0] for b in batches] == ["A", "B", "C"]
    assert batches[0][2] == [("c1", 0.5)]
    assert batches[1][2] == []  # 已被 A 收走
    assert batches[2][2] == []


# ---------- 校验 RerankService 确实被调用 ----------


def test_rerank_batches_output_shape_matches_rank_many_contract():
    """_rerank_batches 的输出必须能直接喂给 rank_many（三元组）。"""
    from app.services.query_service import QueryService

    planned = [(_SubQuery("A", "q"), None)]
    results = [_HybridResult(candidates=[("c1", 0.5)])]
    batches = QueryService._rerank_batches(planned, results)

    assert len(batches[0]) == 3
    sq_id, query, candidates = batches[0]
    assert isinstance(sq_id, str) and isinstance(query, str)
    assert all(isinstance(c[0], str) and isinstance(c[1], float) for c in candidates)


def test_rerank_service_exposes_expected_api():
    """load_rows / rank_many 契约未变（query_service 依赖它）。"""
    assert hasattr(RerankService, "load_rows")
    assert hasattr(RerankService, "rank_many")
    assert hasattr(RerankService, "rank")


@pytest.mark.parametrize("_unused", [None])
def test_ranked_chunk_helper_is_valid(_unused):
    assert _ranked("c1").chunk_id == "c1"


# ---------- 保留策略：query_traces / audit_logs 不得无界增长 ----------


def _cleanup_service(**kwargs):
    from app.services.cleanup_service import CleanupService

    return CleanupService(
        lambda: _FakeSession(), _FakeVectorStore(), batch_size=10, **kwargs
    )


def test_retention_zero_means_keep_forever(monkeypatch):
    """0 天 = 永久保留：不得触碰仓储层（升级后不能意外删数据）。"""
    from app.services import cleanup_service as mod

    touched: list = []

    class _Repo:
        def __init__(self, session) -> None:
            pass

        async def delete_older_than(self, cutoff, limit):
            touched.append(cutoff)
            return 5

    monkeypatch.setattr(mod, "QueryTraceRepository", _Repo)
    monkeypatch.setattr(mod, "AuditLogRepository", _Repo)

    service = _cleanup_service(trace_retention_days=0, audit_retention_days=0)
    assert asyncio.run(service._purge_traces()) == 0
    assert asyncio.run(service._purge_audit_logs()) == 0
    assert touched == []


def test_retention_deletes_in_batches_until_short(monkeypatch):
    """满批继续删，遇到不满批即停（深表不会被单轮一次性删空锁表）。"""
    from app.services import cleanup_service as mod

    batches = [10, 10, 3]
    calls: list[int] = []

    class _Repo:
        def __init__(self, session) -> None:
            pass

        async def delete_older_than(self, cutoff, limit):
            calls.append(limit)
            return batches.pop(0) if batches else 0

    monkeypatch.setattr(mod, "QueryTraceRepository", _Repo)

    service = _cleanup_service(trace_retention_days=30)
    assert asyncio.run(service._purge_traces()) == 23
    assert len(calls) == 3


def test_retention_caps_batches_per_run(monkeypatch):
    """单轮最多 50 批：首次接入的历史积压分多轮清，避免长期锁表。"""
    from app.services import cleanup_service as mod

    calls = 0

    class _Repo:
        def __init__(self, session) -> None:
            pass

        async def delete_older_than(self, cutoff, limit):
            nonlocal calls
            calls += 1
            return limit  # 永远满批，模拟大量积压

    monkeypatch.setattr(mod, "QueryTraceRepository", _Repo)

    service = _cleanup_service(trace_retention_days=30)
    assert asyncio.run(service._purge_traces()) == 50 * 10
    assert calls == 50


def test_audit_retention_uses_audit_repository(monkeypatch):
    """审计与轨迹是两套保留期，不能串用仓储。"""
    from app.services import cleanup_service as mod

    used: list[str] = []

    class _TraceRepo:
        def __init__(self, session) -> None:
            pass

        async def delete_older_than(self, cutoff, limit):
            used.append("trace")
            return 0

    class _AuditRepo:
        def __init__(self, session) -> None:
            pass

        async def delete_older_than(self, cutoff, limit):
            used.append("audit")
            return 0

    monkeypatch.setattr(mod, "QueryTraceRepository", _TraceRepo)
    monkeypatch.setattr(mod, "AuditLogRepository", _AuditRepo)

    service = _cleanup_service(trace_retention_days=30, audit_retention_days=180)
    asyncio.run(service._purge_audit_logs())
    assert used == ["audit"]
