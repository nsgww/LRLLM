"""Metrics 渲染测试（12 §2.5）。"""

from app.observability.metrics import _Metrics


def test_metrics_render_prometheus_text():
    m = _Metrics()
    m.inc("foo_total")
    m.inc("bar_total", {"tool": "x"}, 2)
    out = m.render()
    assert "# TYPE foo_total counter" in out
    assert "foo_total 1" in out
    assert 'bar_total{tool="x"} 2' in out


def test_histogram_renders_cumulative_buckets():
    """histogram 的桶必须是累计计数，且带 +Inf/sum/count。"""
    m = _Metrics()
    m.observe("req_ms", 3, {"path": "/v1/query"})      # <=5
    m.observe("req_ms", 40, {"path": "/v1/query"})     # <=50
    m.observe("req_ms", 9000, {"path": "/v1/query"})   # <=10000

    out = m.render()

    assert "# TYPE req_ms histogram" in out
    # le=5 只有第一条；le=50 累计两条；le=10000 累计三条
    assert 'req_ms_bucket{path="/v1/query",le="5"} 1' in out
    assert 'req_ms_bucket{path="/v1/query",le="50"} 2' in out
    assert 'req_ms_bucket{path="/v1/query",le="10000"} 3' in out
    assert 'req_ms_bucket{path="/v1/query",le="+Inf"} 3' in out
    assert 'req_ms_count{path="/v1/query"} 3' in out
    # 9043 毫秒合计
    assert 'req_ms_sum{path="/v1/query"} 9043.0' in out


def test_histogram_without_labels():
    m = _Metrics()
    m.observe("bare_ms", 7)
    out = m.render()
    assert 'bare_ms_bucket{le="10"} 1' in out
    assert 'bare_ms_bucket{le="+Inf"} 1' in out
    assert "bare_ms_count 1" in out


def test_counter_and_histogram_coexist():
    m = _Metrics()
    m.inc("http_requests_total", {"path": "/x", "status": "200"})
    m.observe("http_request_duration_ms", 12, {"path": "/x"})
    out = m.render()
    assert "# TYPE http_requests_total counter" in out
    assert "# TYPE http_request_duration_ms histogram" in out
    # 每个指标名只允许一条 TYPE 行
    assert out.count("# TYPE http_request_duration_ms histogram") == 1
