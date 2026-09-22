"""语义分块器（第04节第14-17段）。

规则：
- 标题 / 段落 / 列表 / 表格 / 代码块构成语义单元。
- 代码块绝不被拆分；过长的代码块将作为独立的
  超限分块处理（v0.1版本中明确允许）。
- 表格保持完整；raw_content 保留原始 Markdown 格式，text 则保留
  用于检索的规范化表示形式。
- 词元拆分仅适用于超大文本单元。
"""

import hashlib
from dataclasses import dataclass
from typing import Protocol

from app.core.versions import CHUNKER_VERSION
from app.domain.chunk import ChunkType
from app.domain.ingestion import ASTBlock, BlockType, DocumentAST
from app.ingestion.chunkers.token_split import TokenCounter, token_split


@dataclass
class SemanticChunk:
    text: str
    chunk_type: ChunkType
    heading_path: list[str]
    line_start: int
    line_end: int
    token_count: int
    raw_content: str | None = None

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


class SemanticSplitter(Protocol):
    """超长文本的兜底切分器协议；实现见 semantic_split.py。"""

    async def split(self, text: str, max_tokens: int) -> list[str]:
        ...


@dataclass
class ParentChunkNode:
    """父子结构节点：父块为 None 表示该子块独立成块（代码 / 表格）。"""

    parent: SemanticChunk | None
    child: SemanticChunk


class SemanticChunker:
    """语义切块器（04 节 14-17、17.1）。

    - chunk()：平坦切块，只产出检索用子块。
    - chunk_with_parents()：按更大预算做第二遍聚合形成父块；
      子块负责检索，父块负责在 Context 中提供完整上下文。
    """

    version = CHUNKER_VERSION

    def __init__(
        self,
        max_tokens: int,
        counter: TokenCounter | None = None,
        splitter: SemanticSplitter | None = None,
    ) -> None:
        self._max_tokens = max_tokens
        self._counter = counter or TokenCounter()
        self._splitter = splitter

    async def chunk(self, ast: DocumentAST) -> list[SemanticChunk]:
        """平坦切块：只产出检索用子块。"""
        return await self._chunk_flat(ast, self._max_tokens)

    async def chunk_with_parents(
        self,
        ast: DocumentAST,
        parent_max_tokens: int,
    ) -> list[ParentChunkNode]:
        """父子切块（04 节 17.1）：两遍聚合后按行范围归属子块到最小父块。

        代码 / 表格自身已是完整语义单元，不再归属父块。
        """
        children = await self._chunk_flat(ast, self._max_tokens)
        parents = await self._chunk_flat(ast, parent_max_tokens)
        nodes: list[ParentChunkNode] = []
        for child in children:
            if child.chunk_type in (ChunkType.CODE, ChunkType.TABLE):
                nodes.append(ParentChunkNode(parent=None, child=child))
                continue
            nodes.append(ParentChunkNode(parent=_find_container(child, parents), child=child))
        return nodes

    async def _chunk_flat(self, ast: DocumentAST, max_tokens: int) -> list[SemanticChunk]:
        chunks: list[SemanticChunk] = []
        pending: list[ASTBlock] = []  # accumulated text units

        async def flush_pending() -> None:
            nonlocal pending
            if not pending:
                return
            await self._emit_text_units(pending, chunks, max_tokens)
            pending = []

        for block in ast.blocks:
            if block.type == BlockType.HEADING:
                await flush_pending()
                continue
            if block.type == BlockType.CODE_BLOCK:
                await flush_pending()
                chunks.append(self._code_chunk(block))
                continue
            if block.type == BlockType.TABLE:
                await flush_pending()
                chunks.append(self._table_chunk(block))
                continue
            pending.append(block)

        await flush_pending()
        return chunks

    async def _emit_text_units(
        self,
        blocks: list[ASTBlock],
        out: list[SemanticChunk],
        max_tokens: int,
    ) -> None:
        current_parts: list[str] = []
        current_path: list[str] = []
        line_start = blocks[0].line_start
        line_end = blocks[0].line_end

        def flush() -> None:
            nonlocal current_parts, line_start, line_end
            if not current_parts:
                return
            text = "\n\n".join(current_parts)
            out.append(
                SemanticChunk(
                    text=text,
                    chunk_type=ChunkType.TEXT,
                    heading_path=current_path,
                    line_start=line_start,
                    line_end=line_end,
                    token_count=self._counter.count(text),
                )
            )
            current_parts = []

        for block in blocks:
            block_type = ChunkType.LIST if block.type == BlockType.LIST else ChunkType.TEXT
            # heading context change closes the current chunk
            if current_parts and block.heading_path != current_path:
                flush()
            candidate = "\n\n".join([*current_parts, block.content]) if current_parts else block.content
            if current_parts and self._counter.count(candidate) > max_tokens:
                flush()
            if not current_parts:
                current_path = block.heading_path
                line_start = block.line_start
            if self._counter.count(block.content) > max_tokens and not current_parts:
                # 单个语义单元超预算：优先语义断点切分，否则退回句子边界切分
                pieces = await self._split_oversized(block.content, max_tokens)
                for piece in pieces:
                    out.append(
                        SemanticChunk(
                            text=piece,
                            chunk_type=block_type,
                            heading_path=block.heading_path,
                            line_start=block.line_start,
                            line_end=block.line_end,
                            token_count=self._counter.count(piece),
                        )
                    )
                current_path = []
                continue
            current_parts.append(block.content)
            line_end = block.line_end

        flush()

    async def _split_oversized(self, text: str, max_tokens: int) -> list[str]:
        if self._splitter is not None:
            return await self._splitter.split(text, max_tokens)
        return token_split(text, max_tokens, self._counter)

    def _code_chunk(self, block: ASTBlock) -> SemanticChunk:
        # never split, even when over budget (04 section 16)
        return SemanticChunk(
            text=block.content,
            chunk_type=ChunkType.CODE,
            heading_path=block.heading_path,
            line_start=block.line_start,
            line_end=block.line_end,
            token_count=self._counter.count(block.content),
        )

    def _table_chunk(self, block: ASTBlock) -> SemanticChunk:
        return SemanticChunk(
            text=_normalize_table(block.content),
            chunk_type=ChunkType.TABLE,
            heading_path=block.heading_path,
            line_start=block.line_start,
            line_end=block.line_end,
            token_count=self._counter.count(block.content),
            raw_content=block.content,
        )


def _find_container(
    child: SemanticChunk,
    parents: list[SemanticChunk],
) -> SemanticChunk | None:
    """行范围能完整容纳子块、且类型一致的最小父块。"""
    best: SemanticChunk | None = None
    for parent in parents:
        if parent.chunk_type != child.chunk_type:
            continue
        if parent.line_start > child.line_start or parent.line_end < child.line_end:
            continue
        if best is None or (parent.line_end - parent.line_start) < (best.line_end - best.line_start):
            best = parent
    return best


def _normalize_table(raw: str) -> str:
    """Raw markdown table -> readable 'col: value' lines for retrieval (04 section 17)."""
    rows = [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in raw.splitlines()
        if line.strip()
    ]
    rows = [r for r in rows if not all(set(c) <= set("-: ") for c in r)]  # drop separator
    if not rows:
        return raw
    header, body = rows[0], rows[1:]
    lines = []
    for row in body:
        pairs = [f"{h}: {v}" for h, v in zip(header, row, strict=False) if v]
        lines.append("; ".join(pairs))
    return "\n".join(lines) if lines else raw
