"""可脚本计算的检索指标（07-evaluation-spec 第 5 节）。

指标基于 `reranked_results` 计算，k 与 `rerank_top_n` 对齐（默认 10）。
断言对象是 Heading Path 等稳定标识，不是 chunk_id。
"""

from collections.abc import Collection, Sequence


def recall_at_k(ranked: Sequence[str], relevant: Collection[str], k: int) -> float:
    """期望 Evidence 是否出现在 top_k 召回中。"""
    relevant_set = set(relevant)
    if not relevant_set or k <= 0:
        return 0.0
    return len(set(ranked[:k]) & relevant_set) / len(relevant_set)


def precision_at_k(ranked: Sequence[str], relevant: Collection[str], k: int) -> float:
    """top_k 中相关 Chunk 占比。"""
    if k <= 0:
        return 0.0
    top = ranked[:k]
    if not top:
        return 0.0
    relevant_set = set(relevant)
    return sum(1 for item in top if item in relevant_set) / len(top)


def mrr(ranked: Sequence[str], relevant: Collection[str]) -> float:
    """首个正确 Evidence 的倒数排名。"""
    relevant_set = set(relevant)
    for rank, item in enumerate(ranked, start=1):
        if item in relevant_set:
            return 1.0 / rank
    return 0.0
