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
