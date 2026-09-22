"""Section hierarchy construction (04 section 13, 09 section 5)."""

from app.domain.ingestion import ASTBlock, BlockType
from app.ingestion.pipeline import _build_sections


def _heading(text, path, level, start, end):
    return ASTBlock(
        type=BlockType.HEADING,
        content=text,
        heading_path=list(path),
        level=level,
        line_start=start,
        line_end=end,
    )


def test_parent_offsets_resolve_nested_headings():
    blocks = [
        _heading("A", ["A"], 1, 1, 10),
        _heading("B", ["A", "B"], 2, 3, 5),
        _heading("C", ["A", "C"], 2, 7, 9),
        ASTBlock(type=BlockType.PARAGRAPH, content="tail", line_start=10, line_end=12),
    ]

    sections, parents, paths = _build_sections(blocks, document_id="doc")

    assert [s.heading for s in sections] == ["A", "B", "C"]
    assert parents == [None, 0, 0]
    assert paths == [("A",), ("A", "B"), ("A", "C")]
    # A spans until the document end; B ends right before its sibling C.
    assert sections[0].line_end == 12
    assert sections[1].line_end == 6
    # Parent ids are resolved from the flushed rows, not at construction time.
    assert all(s.parent_section_id is None for s in sections)


def test_top_level_sections_have_no_parent():
    blocks = [_heading("A", ["A"], 1, 1, 2), _heading("B", ["B"], 1, 3, 4)]
    _, parents, _ = _build_sections(blocks, document_id="doc")
    assert parents == [None, None]
