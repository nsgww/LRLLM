"""轻量 Metrics（12-agent-platform-spec §2.5）。

零第三方依赖的 Prometheus 文本计数器。输出遵守文本协议：
每个指标名仅一条 ``# TYPE`` 行；label 值做转义（``\\`` ``"`` 换行），
避免畸形输出。计数点：HTTP 请求、策略拒绝、审计失败等。
"""

from __future__ import annotations

import threading


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class _Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = {}

    def inc(self, name: str, labels: dict[str, str] | None = None, n: int = 1) -> None:
        if labels:
            label_str = "{" + ",".join(
                f'{k}="{_escape_label(str(v))}"' for k, v in sorted(labels.items())
            ) + "}"
        else:
            label_str = ""
        key = f"{name}{label_str}"
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + n

    def render(self) -> str:
        # 文本协议：每个指标名只允许一条 # TYPE 行（按名字分组后集中输出）。
        grouped: dict[str, list[tuple[str, int]]] = {}
        with self._lock:
            for key, value in self._counters.items():
                grouped.setdefault(key.split("{", 1)[0], []).append((key, value))
        lines: list[str] = []
        for name in sorted(grouped):
            lines.append(f"# TYPE {name} counter")
            for key, value in sorted(grouped[name]):
                lines.append(f"{key} {value}")
        return "\n".join(lines) + "\n"


_metrics = _Metrics()


def get_metrics() -> _Metrics:
    return _metrics
