"""Semantic chunker contract tests (04 sections 14-17)."""

from app.domain.chunk import ChunkType
from app.domain.ingestion import DocumentAST
from app.ingestion.chunkers.semantic import SemanticChunker
from app.ingestion.chunkers.token_split import TokenCounter
from app.ingestion.parsers.markdown import MarkdownParser


class WordCounter(TokenCounter):
    """Deterministic counter: 1 word = 1 token."""

    def count(self, text: str) -> int:
        return len(text.split())


async def _parse(md: str) -> DocumentAST:
    return await MarkdownParser().parse(md.encode("utf-8"), {})


def _chunker(max_tokens: int = 10) -> SemanticChunker:
    return SemanticChunker(max_tokens=max_tokens, counter=WordCounter())


async def test_code_block_never_split_even_when_over_budget():
    code = " ".join(f"word{i}" for i in range(40))
    ast = await _parse(f"# Guide\n\n```python\n{code}\n```\n")
    chunks = _chunker(max_tokens=5).chunk(ast)
    assert len(chunks) == 1
    assert chunks[0].chunk_type == ChunkType.CODE
    # fences count too; the point is the over-budget block stays whole
    assert chunks[0].token_count > 5
    assert code in chunks[0].text


async def test_table_chunk_keeps_raw_content():
    md = "# Guide\n\n| Field | Meaning |\n|---|---|\n| role | message role |\n"
    ast = await _parse(md)
    chunks = _chunker().chunk(ast)
    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.chunk_type == ChunkType.TABLE
    assert chunk.raw_content is not None and "| role | message role |" in chunk.raw_content
    # normalized text used for retrieval, raw kept for context
    assert "Field: role" in chunk.text
    assert "|" not in chunk.text


async def test_heading_change_closes_current_chunk():
    md = "# A\n\nfirst paragraph text\n\n# B\n\nsecond paragraph text\n"
    ast = await _parse(md)
    chunks = _chunker().chunk(ast)
    assert len(chunks) == 2
    assert chunks[0].heading_path == ["A"]
    assert chunks[1].heading_path == ["B"]


async def test_oversized_paragraph_split_at_sentence_boundaries():
    paragraph = "alpha beta gamma. " * 6  # 24 words, 6 sentences
    ast = await _parse(f"# Guide\n\n{paragraph}\n")
    chunks = _chunker(max_tokens=10).chunk(ast)
    assert len(chunks) >= 2
    assert all(c.token_count <= 10 for c in chunks)
    assert all(c.chunk_type == ChunkType.TEXT for c in chunks)


async def test_content_hash_stable():
    ast = await _parse("# Guide\n\nsame text\n")
    first = _chunker().chunk(ast)[0].content_hash
    second = _chunker().chunk(ast)[0].content_hash
    assert first == second
