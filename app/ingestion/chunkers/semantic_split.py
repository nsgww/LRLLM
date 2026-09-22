"""语义切分：基于句子 Embedding 相似度的断点检测（04 节 15.1）。

适用场景：单个语义单元（段落）超过 token 预算时的兜底切分。
与 token_split 的顺序打包不同，这里先对句子批量取向量，
在相邻句子相似度低于阈值的位置断开，尽量让每一片语义内聚。

代价是入库阶段额外的 Embedding 调用，因此默认关闭
（RAG_SEMANTIC_SPLIT_ENABLED=false），关闭时仍走 token_split。
"""

import math
import re

from app.embedding.interface import EmbeddingModel
from app.ingestion.chunkers.token_split import TokenCounter, token_split

# 与 token_split 相同的句子边界；保持两处断句口径一致
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[。！？.!?;；\n])")


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class EmbeddingSentenceSplitter:
    """语义断点切分器。实现 SemanticSplitter 协议（见 semantic.py）。"""

    def __init__(
        self,
        embedding: EmbeddingModel,
        counter: TokenCounter | None = None,
        threshold: float = 0.5,
    ) -> None:
        self._embedding = embedding
        self._counter = counter or TokenCounter()
        self._threshold = threshold

    async def split(self, text: str, max_tokens: int) -> list[str]:
        sentences = [s for s in _SENTENCE_BOUNDARY_RE.split(text) if s.strip()]
        if len(sentences) <= 1:
            return [text]

        try:
            vectors = await self._embedding.embed_documents(sentences)
        except Exception:
            # Embedding 不可用不应阻断入库：退回顺序切分
            return token_split(text, max_tokens, self._counter)

        # 相邻句子相似度低谷即候选断点
        breaks: set[int] = set()
        for i in range(1, len(sentences)):
            if _cosine(vectors[i - 1], vectors[i]) < self._threshold:
                breaks.add(i)

        # 按断点分段后打包，仍受 token 预算约束；装不下的段退回 token_split
        groups: list[list[str]] = []
        current: list[str] = [sentences[0]]
        for i in range(1, len(sentences)):
            if i in breaks:
                groups.append(current)
                current = []
            current.append(sentences[i])
        groups.append(current)

        pieces: list[str] = []
        for group in groups:
            text_piece = "".join(group)
            if self._counter.count(text_piece) > max_tokens:
                pieces.extend(token_split(text_piece, max_tokens, self._counter))
            else:
                pieces.append(text_piece)
        return [p for p in pieces if p.strip()]
