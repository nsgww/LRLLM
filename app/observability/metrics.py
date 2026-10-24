"""轻量 Metrics（12-agent-platform-spec §2.5）。

零第三方依赖的 Prometheus 文本暴露，支持 counter 与 histogram：

- counter：``inc(name, labels)``
- histogram：``observe(name, value_ms, labels)``，固定桶（毫秒）

输出遵守文本协议：每个指标名仅一条 ``# TYPE`` 行；label 值做转义
（``\\`` ``"`` 换行），避免畸形输出。

基数控制：调用方必须用**路由模板**（``/v1/documents/{id}``）而非原始 path
作 label，否则任意随机 URL 都能注入新 label 撑爆内存（见 main.py 中间件）。
"""

from __future__ import annotations

import threading

# 请求耗时桶（毫秒）：覆盖从缓存命中到慢 LLM 生成的量级。
_DEFAULT_BUCKETS_MS: tuple[float, ...] = (
    5,
    10,
    25,
    50,
    100,
    250,
    500,
    1000,
    2500,
    5000,
    10000,
    30000,
)


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _labels(labels: dict[str, str] | None) -> str:
    if not labels:
        return ""
    return "{" + ",".join(
        f'{k}="{_escape_label(str(v))}"' for k, v in sorted(labels.items())
    ) + "}"


class _Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = {}
        # histogram key -> {"buckets": [n_leq], "sum": float, "count": int}
        self._histograms: dict[str, dict] = {}

    def inc(self, name: str, labels: dict[str, str] | None = None, n: int = 1) -> None:
        key = f"{name}{_labels(labels)}"
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + n

    def observe(
        self,
        name: str,
        value: float,
        labels: dict[str, str] | None = None,
        buckets: tuple[float, ...] = _DEFAULT_BUCKETS_MS,
    ) -> None:
        """记录一次观测值（毫秒），累加到 histogram 桶。"""
        key = f"{name}{_labels(labels)}"
        with self._lock:
            entry = self._histograms.get(key)
            if entry is None:
                entry = {
                    "buckets": [0] * len(buckets),
                    "bounds": buckets,
                    "sum": 0.0,
                    "count": 0,
                }
                self._histograms[key] = entry
            for index, bound in enumerate(entry["bounds"]):
                if value <= bound:
                    # 只计入第一个满足的桶；渲染时再累加成 Prometheus 语义的
                    # 累计桶。若这里对所有 bound >= value 都自增，渲染会二次累加。
                    entry["buckets"][index] += 1
                    break
            entry["sum"] += value
            entry["count"] += 1

    def render(self) -> str:
        lines: list[str] = []

        grouped: dict[str, list[tuple[str, int]]] = {}
        with self._lock:
            for key, value in self._counters.items():
                grouped.setdefault(key.split("{", 1)[0], []).append((key, value))
            histograms = {
                key: {
                    "buckets": list(entry["buckets"]),
                    "bounds": tuple(entry["bounds"]),
                    "sum": entry["sum"],
                    "count": entry["count"],
                }
                for key, entry in self._histograms.items()
            }

        for name in sorted(grouped):
            lines.append(f"# TYPE {name} counter")
            for key, value in sorted(grouped[name]):
                lines.append(f"{key} {value}")

        # histogram 必须以 _bucket/_sum/_count 后缀命名，每个桶是累计计数。
        for key in sorted(histograms):
            entry = histograms[key]
            name, _, label_body = key.partition("{")
            suffix = f"{{{label_body}" if label_body else ""
            lines.append(f"# TYPE {name} histogram")
            cumulative = 0
            for index, bound in enumerate(entry["bounds"]):
                cumulative += entry["buckets"][index]
                if suffix:
                    bucket_labels = suffix[:-1] + f',le="{bound}"}}'
                else:
                    bucket_labels = f'{{le="{bound}"}}'
                lines.append(f"{name}_bucket{bucket_labels} {cumulative}")
            if suffix:
                infinity_labels = suffix[:-1] + ',le="+Inf"}'
            else:
                infinity_labels = '{le="+Inf"}'
            lines.append(f"{name}_bucket{infinity_labels} {entry['count']}")
            lines.append(f"{name}_sum{suffix} {entry['sum']}")
            lines.append(f"{name}_count{suffix} {entry['count']}")

        return "\n".join(lines) + "\n"


_metrics = _Metrics()


def get_metrics() -> _Metrics:
    return _metrics
