"""解析器路由与 HTML/PDF 解析契约测试（04 节 6-10、23）。"""

import pytest

from app.core.errors import IngestionError
from app.domain.ingestion import BlockType
from app.ingestion.parsers import parser_for
from app.ingestion.parsers.html import HtmlParser
from app.ingestion.parsers.markdown import MarkdownParser
from app.ingestion.parsers.pdf import PdfParser

HTML_SAMPLE = """<!DOCTYPE html>
<html>
<head><title>Guide</title></head>
<body>
<h1>MCP</h1>
<p>Intro paragraph.</p>
<h2>Prompt</h2>
<p>Write prompts like this:</p>
<pre>{"role": "system"}</pre>
<table>
<tr><th>Field</th><th>Meaning</th></tr>
<tr><td>role</td><td>message role</td></tr>
</table>
<ul>
<li>item one</li>
<li>item two</li>
</ul>
<script>var ignored = true;</script>
</body>
</html>
"""


def test_routing_by_hint_suffix():
    assert isinstance(parser_for("anything", hint="doc.md"), MarkdownParser)
    assert isinstance(parser_for("anything", hint="doc.html"), HtmlParser)
    assert isinstance(parser_for("anything", hint="doc.pdf"), PdfParser)


def test_routing_by_content_sniffing():
    assert isinstance(parser_for("%PDF-1.7 binary..."), PdfParser)
    assert isinstance(parser_for("<!DOCTYPE html><html>...</html>"), HtmlParser)
    assert isinstance(parser_for("# plain markdown\n\ntext"), MarkdownParser)


def test_routing_hint_wins_over_content():
    # 内容与扩展名不一致时以显式提示为准（上传文件名即文档来源）
    assert isinstance(parser_for("<html>x</html>", hint="doc.md"), MarkdownParser)


async def test_html_blocks_and_heading_path():
    ast = await HtmlParser().parse(HTML_SAMPLE.encode("utf-8"), {})
    types = [b.type for b in ast.blocks]
    assert BlockType.HEADING in types
    assert BlockType.CODE_BLOCK in types
    assert BlockType.TABLE in types
    assert BlockType.LIST in types

    prompt_para = next(
        b for b in ast.blocks
        if b.type == BlockType.PARAGRAPH and "Write prompts" in b.content
    )
    assert prompt_para.heading_path == ["MCP", "Prompt"]

    code = next(b for b in ast.blocks if b.type == BlockType.CODE_BLOCK)
    assert '{"role": "system"}' in code.content

    table = next(b for b in ast.blocks if b.type == BlockType.TABLE)
    assert "| role | message role |" in table.content

    # script 内容不得进入任何块
    assert all("ignored" not in b.content for b in ast.blocks)


async def test_html_title_from_title_tag_or_heading():
    ast = await HtmlParser().parse(HTML_SAMPLE.encode("utf-8"), {})
    assert ast.title == "MCP"


async def test_html_empty_document_rejected():
    with pytest.raises(IngestionError) as exc_info:
        await HtmlParser().parse(b"   ", {})
    assert exc_info.value.code == "FILE_EMPTY"


async def test_pdf_parser_blank_pdf_fails_cleanly():
    pytest.importorskip("pypdf")
    import io

    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buffer = io.BytesIO()
    writer.write(buffer)
    pdf_bytes = buffer.getvalue()

    # 空白页 PDF 无可抽取文本，必须以 FILE_EMPTY 失败而不是崩溃
    with pytest.raises(IngestionError) as exc_info:
        await PdfParser().parse(pdf_bytes, {})
    assert exc_info.value.code in ("FILE_EMPTY", "PARSER_FAILED")
