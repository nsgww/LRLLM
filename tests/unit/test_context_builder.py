"""Context builder contract tests (02 sections 15-17, 06 section 8)."""

from app.core.config import Settings
from app.domain.retrieval import RankedChunk
from app.ingestion.chunkers.token_split import TokenCounter
from app.retrieval.context.builder import ContextBuilder


class WordCounter(TokenCounter):
    def count(self, text: str) -> int:
        return len(text.split())


def _chunk(
    chunk_id: str,
    version: str | None = "0.5.3",
    text: str = "body text",
    raw_content: str | None = None,
    parent_chunk_id: str | None = None,
    parent_content: str | None = None,
) -> RankedChunk:
    return RankedChunk(
        chunk_id=chunk_id,
        document_id="doc",
        text=text,
        score=1.0,
        heading_path="MCP / Guide",
        line_start=1,
        line_end=2,
        raw_content=raw_content,
        parent_chunk_id=parent_chunk_id,
        parent_content=parent_content,
        product="MCP",
        version=version,
    )


def _builder(per_version_cap: int = 5, budget: int = 10000) -> ContextBuilder:
    settings = Settings(per_version_cap=per_version_cap, context_token_budget=budget)
    return ContextBuilder(settings, counter=WordCounter())


def test_dedup_by_chunk_id():
    built = _builder().build([_chunk("c1"), _chunk("c1"), _chunk("c2")], version_specified=True)
    assert [c.chunk_id for c in built.chunks] == ["c1", "c2"]


def test_per_version_cap_and_boundaries_when_version_not_specified():
    chunks = [_chunk("a", "0.5.3"), _chunk("b", "0.5.3"), _chunk("c", "0.6.0")]
    built = _builder(per_version_cap=1).build(chunks, version_specified=False)
    assert [c.chunk_id for c in built.chunks] == ["a", "c"]
    assert "=== MCP v0.5.3 ===" in built.text
    assert "=== MCP v0.6.0 ===" in built.text


def test_no_cap_no_boundary_when_version_specified():
    chunks = [_chunk("a", "0.5.3"), _chunk("b", "0.5.3")]
    built = _builder(per_version_cap=1).build(chunks, version_specified=True)
    assert [c.chunk_id for c in built.chunks] == ["a", "b"]
    assert "===" not in built.text


def test_token_budget_stops_at_first_overflow():
    """02 section 15: higher-ranked evidence wins, so the first unit that no
    longer fits ends selection instead of letting lower-ranked ones jump in."""
    chunks = [
        _chunk("one", text="one two three"),    # 3 tokens, always kept (first)
        _chunk("two", text="four five six"),    # 3 tokens, exceeds remaining 2
        _chunk("three", text="seven eight"),    # 2 tokens, would fit but ranks lower
    ]
    built = _builder(budget=5).build(chunks, version_specified=True)
    assert [c.chunk_id for c in built.chunks] == ["one"]
    assert built.token_count == 3


def test_table_uses_raw_content_in_context():
    chunk = _chunk("t", text="Field: role", raw_content="| Field |\n| role |")
    built = _builder().build([chunk], version_specified=True)
    assert "| Field |" in built.text
    assert "Field: role" not in built.text


def test_heading_path_included_with_each_chunk():
    built = _builder().build([_chunk("c1")], version_specified=True)
    assert "[MCP / Guide]" in built.text


def _child_with_parent(chunk_id: str, parent_id: str = "p1") -> RankedChunk:
    return _chunk(
        chunk_id,
        text="child body",
        parent_chunk_id=parent_id,
        parent_content="full parent section text",
    )


def test_parent_expansion_prefers_parent_content():
    built = _builder().build([_child_with_parent("c1")], version_specified=True)
    assert "full parent section text" in built.text
    assert "child body" not in built.text


def test_sibling_children_collapse_to_single_parent():
    chunks = [_child_with_parent("c1"), _child_with_parent("c2"), _chunk("c3")]
    built = _builder().build(chunks, version_specified=True)
    assert [c.chunk_id for c in built.chunks] == ["c1", "c3"]
    assert built.text.count("full parent section text") == 1


def test_parent_over_budget_falls_back_to_child_text():
    """04 §17.1：父块全文超预算时回退到子块自身文本，而非整条丢弃。"""
    big_parent = " ".join(f"w{i}" for i in range(20))  # 20 tokens > budget 10
    chunk = _child_with_parent("c1")  # text="child body" = 2 tokens
    chunk.parent_content = big_parent
    built = _builder(budget=10).build([chunk], version_specified=True)
    assert [c.chunk_id for c in built.chunks] == ["c1"]
    assert "child body" in built.text
    assert big_parent not in built.text


def test_child_also_over_budget_is_dropped():
    """子块自身也超预算时，该命中被丢弃（不强行注入）。"""
    big_parent = " ".join(f"w{i}" for i in range(20))
    chunk = _child_with_parent("c1")
    chunk.parent_content = big_parent
    chunk.text = " ".join(f"t{i}" for i in range(30))  # 30 tokens > budget 10
    built = _builder(budget=10).build([chunk], version_specified=True)
    assert built.chunks == []
    assert built.text == ""


def test_expansion_disabled_keeps_child_text():
    settings = Settings(context_expand_to_parent=False)
    builder = ContextBuilder(settings, counter=WordCounter())
    built = builder.build([_child_with_parent("c1")], version_specified=True)
    assert "child body" in built.text
    assert "full parent section text" not in built.text


def test_chunk_without_parent_content_falls_back_to_own_text():
    # 旧文档（接线前入库）没有父块，仍按自身内容进入上下文
    chunk = _chunk("legacy", text="legacy body", parent_chunk_id="p1")
    built = _builder().build([chunk], version_specified=True)
    assert "legacy body" in built.text
