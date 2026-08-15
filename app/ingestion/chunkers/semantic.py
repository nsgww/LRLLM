"""Semantic chunker (04 sections 14-17).

Rules:
- Heading / Paragraph / List / Table / Code Block form semantic units.
- Code blocks are never split; an overlong code block becomes its own
  over-budget chunk (explicitly allowed in v0.1).
- Tables stay whole; raw_content keeps the raw markdown, text keeps the
  normalized representation used for retrieval.
- Token split only applies to oversized text units.
"""

import hashlib
from dataclasses import dataclass

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


class SemanticChunker:
    version = CHUNKER_VERSION

    def __init__(self, max_tokens: int, counter: TokenCounter | None = None) -> None:
        self._max_tokens = max_tokens
        self._counter = counter or TokenCounter()

    def chunk(self, ast: DocumentAST) -> list[SemanticChunk]:
        chunks: list[SemanticChunk] = []
        pending: list[ASTBlock] = []  # accumulated text units

        def flush_pending() -> None:
            nonlocal pending
            if not pending:
                return
            self._emit_text_units(pending, chunks)
            pending = []

        for block in ast.blocks:
            if block.type == BlockType.HEADING:
                flush_pending()
                continue
            if block.type == BlockType.CODE_BLOCK:
                flush_pending()
                chunks.append(self._code_chunk(block))
                continue
            if block.type == BlockType.TABLE:
                flush_pending()
                chunks.append(self._table_chunk(block))
                continue
            pending.append(block)

        flush_pending()
        return chunks

    def _emit_text_units(self, blocks: list[ASTBlock], out: list[SemanticChunk]) -> None:
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
            if current_parts and self._counter.count(candidate) > self._max_tokens:
                flush()
            if not current_parts:
                current_path = block.heading_path
                line_start = block.line_start
            if self._counter.count(block.content) > self._max_tokens and not current_parts:
                # oversized single unit: token split as fallback
                for piece in token_split(block.content, self._max_tokens, self._counter):
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
