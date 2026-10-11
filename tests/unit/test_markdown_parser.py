"""Markdown parser contract tests (04 sections 6-10)."""

import pytest

from app.core.errors import IngestionError
from app.domain.ingestion import BlockType
from app.ingestion.parsers.markdown import MarkdownParser

SAMPLE = """---
title: MCP Prompt Guide
product: MCP
version: v0.5.3
---

# MCP

Intro paragraph.

## Prompt

Write prompts like this:

```json
{"role": "system"}
```

| Field | Meaning |
|---|---|
| role | message role |

- item one
- item two
"""


async def _parse(source: bytes, metadata: dict | None = None):
    return await MarkdownParser().parse(source, metadata or {})


async def test_front_matter_extracted_and_title_from_front_matter():
    ast = await _parse(SAMPLE.encode("utf-8"))
    front_matter = ast.metadata["front_matter"]
    assert front_matter["title"] == "MCP Prompt Guide"
    assert front_matter["product"] == "MCP"
    assert front_matter["version"] == "v0.5.3"
    assert ast.title == "MCP Prompt Guide"


async def test_heading_path_and_line_ranges_account_for_front_matter():
    ast = await _parse(SAMPLE.encode("utf-8"))
    headings = [b for b in ast.blocks if b.type == BlockType.HEADING]
    assert [(h.content, h.level) for h in headings] == [("MCP", 1), ("Prompt", 2)]
    # front matter occupies lines 1-5, so "# MCP" is on line 7
    assert headings[0].line_start == 7

    paragraph = next(
        b for b in ast.blocks
        if b.type == BlockType.PARAGRAPH and "Write prompts" in b.content
    )
    assert paragraph.heading_path == ["MCP", "Prompt"]
    assert paragraph.line_start == 13
    assert paragraph.line_end == 13


async def test_code_block_kept_intact_with_fences():
    ast = await _parse(SAMPLE.encode("utf-8"))
    code_blocks = [b for b in ast.blocks if b.type == BlockType.CODE_BLOCK]
    assert len(code_blocks) == 1
    block = code_blocks[0]
    assert block.content.startswith("```json")
    assert block.content.endswith("```")
    assert '{"role": "system"}' in block.content
    assert block.line_start == 15
    assert block.line_end == 17


async def test_table_and_list_blocks():
    ast = await _parse(SAMPLE.encode("utf-8"))
    table = next(b for b in ast.blocks if b.type == BlockType.TABLE)
    assert "| role | message role |" in table.content

    list_block = next(b for b in ast.blocks if b.type == BlockType.LIST)
    assert len(list_block.children) == 2
    assert list_block.children[0].type == BlockType.LIST_ITEM


async def test_empty_document_rejected():
    with pytest.raises(IngestionError) as exc_info:
        await _parse(b"  \n  \n")
    assert exc_info.value.code == "FILE_EMPTY"
    assert exc_info.value.stage == "PARSE"


async def test_invalid_utf8_rejected():
    with pytest.raises(IngestionError) as exc_info:
        await _parse(b"\xff\xfe\x00invalid")
    assert exc_info.value.code == "FILE_INVALID"


async def test_title_falls_back_to_first_heading():
    ast = await _parse(b"# Only Heading\n\nbody text\n")
    assert ast.title == "Only Heading"
    assert ast.metadata["front_matter"] == {}


async def test_tilde_fenced_code_block():
    source = b"# Doc\n\n~~~python\nprint('hi')\n~~~\n"
    ast = await _parse(source)
    code = next(b for b in ast.blocks if b.type == BlockType.CODE_BLOCK)
    assert code.content.startswith("~~~python")
    assert code.content.endswith("~~~")
    assert "print('hi')" in code.content


async def test_backtick_fence_does_not_close_tilde_block():
    source = b"# Doc\n\n~~~\na\n```\nb\n~~~\n"
    ast = await _parse(source)
    code_blocks = [b for b in ast.blocks if b.type == BlockType.CODE_BLOCK]
    assert len(code_blocks) == 1
    # the ``` line is content inside the ~~~ block, not a closing fence
    assert "```" in code_blocks[0].content
    assert code_blocks[0].content.rstrip().endswith("~~~")


async def test_indented_code_block():
    source = b"# Doc\n\nIntro.\n\n    def f():\n        return 1\n"
    ast = await _parse(source)
    code = next(b for b in ast.blocks if b.type == BlockType.CODE_BLOCK)
    assert "def f():" in code.content
    assert "    return 1" in code.content  # inner indentation preserved


async def test_indented_list_item_is_not_treated_as_code():
    source = b"- item one\n- item two\n"
    ast = await _parse(source)
    list_block = next(b for b in ast.blocks if b.type == BlockType.LIST)
    assert len(list_block.children) == 2


async def test_front_matter_supports_lists_and_nested_maps():
    source = (
        b"---\n"
        b"title: Guide\n"
        b"product: MCP\n"
        b"tags:\n  - api\n  - prompt\n"
        b"meta:\n  owner: docs\n  lang: zh\n"
        b"---\n\n# Guide\n\nbody\n"
    )
    ast = await _parse(source)
    fm = ast.metadata["front_matter"]
    assert fm["title"] == "Guide"
    assert fm["product"] == "MCP"
    assert fm["tags"] == ["api", "prompt"]
    assert fm["meta"] == {"owner": "docs", "lang": "zh"}
