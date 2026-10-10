"""Per-stage latency trace assembly (06 section 13)."""

import time

from app.tracing.query_trace import QueryTraceBuilder


def _trace() -> QueryTraceBuilder:
    return QueryTraceBuilder(
        knowledge_base_id="00000000-0000-0000-0000-000000000001",
        answer_id="00000000-0000-0000-0000-000000000002",
        raw_query="q",
    )


def test_stage_latencies_accumulate_per_stage():
    trace = _trace()
    trace.start_stage("QUERY_UNDERSTANDING")
    time.sleep(0.01)
    trace.start_stage("QUERY_REWRITE")
    time.sleep(0.01)
    trace.finish_stages()

    assert "QUERY_UNDERSTANDING" in trace.stage_latencies
    assert "QUERY_REWRITE" in trace.stage_latencies
    assert trace.stage_latencies["QUERY_UNDERSTANDING"] >= 5


def test_repeated_stage_visits_accumulate():
    trace = _trace()
    trace.start_stage("RERANKING")
    time.sleep(0.005)
    trace.start_stage("EVIDENCE_CHECK")
    time.sleep(0.005)
    trace.start_stage("RERANKING")
    time.sleep(0.005)
    trace.finish_stages()

    # Reranking was visited twice (e.g. retry); both visits count.
    assert trace.stage_latencies["RERANKING"] >= 10


def test_stage_latencies_persist_to_row():
    trace = _trace()
    trace.start_stage("LLM_GENERATION")
    time.sleep(0.005)
    trace.finish_stages()
    row = trace.to_row()
    assert row["stage_latencies"]["LLM_GENERATION"] >= 1


def test_finish_stages_is_idempotent():
    trace = _trace()
    trace.start_stage("METADATA_FILTER")
    trace.finish_stages()
    first = dict(trace.stage_latencies)
    trace.finish_stages()
    assert trace.stage_latencies == first
