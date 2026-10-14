"""轻量 Metrics（12-agent-platform-spec §2.5）。

零第三方依赖的 Prometheus 文本计数器，避免为核心可观测性引入重依赖。
计数点：HTTP 请求、策略拒绝、wiki 沉淀等。输出经 ``GET /metrics``。
"""

from __future__ import annotations

import threading


class _Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = {}

    def inc(self, name: str, labels: dict[str, str] | None = None, n: int = 1) -> None:
        if labels:
            label_str = "{" + ",".join(
                f'{k}="{v}"' for k, v in sorted(labels.items())
            ) + "}"
        else:
            label_str = ""
        key = f"{name}{label_str}"
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + n

    def render(self) -> str:
        lines: list[str] = []
        with self._lock:
            for key in sorted(self._counters):
                name = key.split("{", 1)[0]
                lines.append(f"# TYPE {name} counter")
                lines.append(f"{key} {self._counters[key]}")
        return "\n".join(lines) + "\n"


_metrics = _Metrics()


def get_metrics() -> _Metrics:
    return _metrics
