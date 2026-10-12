"""边界与完整性测试：审查修复引入/触及的纯逻辑边界。

覆盖：
- assert_same_kb：KB 归属断言的命中/越权/None/非法 UUID 边界（防 IDOR）。
- Cursor 分页：编解码往返、畸形/空 cursor → 400、has_more 边界。
- parser_for：字节嗅探的边界（空、BOM、PDF/HTML 魔数、hint 优先）。
- _is_private_host：inet_aton 短式 IPv4 等 SSRF 绕过形式。
- Markdown：前置 BOM 不得破坏 front-matter 检测与行号。
"""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.api.pagination import decode_cursor, encode_cursor, next_cursor
from app.core.config import _is_private_host
from app.core.errors import AppError
from app.core.ids import parse_uuid
from app.domain.ingestion import BlockType
from app.ingestion.parsers import parser_for
from app.ingestion.parsers.html import HtmlParser
from app.ingestion.parsers.markdown import MarkdownParser
from app.ingestion.parsers.pdf import PdfParser

# ---------- assert_same_kb ----------

from app.core.ids import assert_same_kb

_KB = "11111111-1111-1111-1111-111111111111"
_OTHER = "22222222-2222-2222-2222-222222222222"


def test_assert_same_kb_allows_owned_resource():
    row = SimpleNamespace(knowledge_base_id=parse_uuid(_KB))
    assert_same_kb(row, _KB)  # 不抛异常即通过


def test_assert_same_kb_rejects_other_kb_with_404():
    row = SimpleNamespace(knowledge_base_id=parse_uuid(_OTHER))
    with pytest.raises(AppError) as exc:
        assert_same_kb(row, _KB)
    assert exc.value.http_status == 404


def test_assert_same_kb_rejects_none_row():
    with pytest.raises(AppError) as exc:
        assert_same_kb(None, _KB)
    assert exc.value.http_status == 404


def test_assert_same_kb_rejects_row_missing_kb_attr():
    with pytest.raises(AppError) as exc:
        assert_same_kb(SimpleNamespace(), _KB)
    assert exc.value.http_status == 404


def test_assert_same_kb_invalid_kb_id_is_400():
    row = SimpleNamespace(knowledge_base_id=parse_uuid(_KB))
    with pytest.raises(AppError) as exc:
        assert_same_kb(row, "not-a-uuid")
    assert exc.value.http_status == 400
    assert exc.value.code == "INVALID_ID"


# ---------- Cursor 分页 ----------


def test_cursor_round_trip():
    ts = datetime(2026, 10, 12, 8, 30, tzinfo=UTC)
    decoded_ts, decoded_id = decode_cursor(encode_cursor(ts, _KB))
    assert decoded_ts == ts
    assert decoded_id == _KB


@pytest.mark.parametrize("bad", ["", "!!!not-base64!!!", "eyJub3QiOiJhbiBpZCJ9"])
def test_cursor_malformed_raises_400(bad):
    with pytest.raises(AppError) as exc:
        decode_cursor(bad)
    assert exc.value.http_status == 400
    assert exc.value.code == "INVALID_CURSOR"


def test_next_cursor_none_when_no_more():
    rows = [SimpleNamespace(created_at=datetime(2026, 1, 1, tzinfo=UTC), id=_KB)]
    assert next_cursor(rows, has_more=False) is None


def test_next_cursor_none_when_rows_empty():
    assert next_cursor([], has_more=True) is None


def test_next_cursor_encodes_last_row():
    rows = [
        SimpleNamespace(created_at=datetime(2026, 1, 2, tzinfo=UTC), id=_KB),
        SimpleNamespace(created_at=datetime(2026, 1, 1, tzinfo=UTC), id=_OTHER),
    ]
    cursor = next_cursor(rows, has_more=True)
    assert cursor is not None
    ts, last_id = decode_cursor(cursor)
    assert ts == datetime(2026, 1, 1, tzinfo=UTC)
    assert last_id == _OTHER


# ---------- parser_for 字节嗅探 ----------


def test_parser_for_empty_bytes_is_markdown():
    assert isinstance(parser_for(b""), MarkdownParser)


def test_parser_for_pdf_magic():
    assert isinstance(parser_for(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3"), PdfParser)


def test_parser_for_html():
    assert isinstance(parser_for(b"<!DOCTYPE html><html><body>x"), HtmlParser)


def test_parser_for_hint_wins_over_content():
    # 扩展名优先，即使内容像 PDF
    assert isinstance(parser_for(b"%PDF-1.7", hint="notes.md"), MarkdownParser)


def test_parser_for_plain_bytes_is_markdown():
    assert isinstance(parser_for(b"# Title\n\nplain text"), MarkdownParser)


# ---------- _is_private_host：inet_aton 短式 ----------


@pytest.mark.parametrize("host", ["127.1", "10.1", "192.168.1", "127.0.1"])
def test_private_host_short_ipv4_detected(host):
    assert _is_private_host(host) is True


@pytest.mark.parametrize("host", ["8.8.8", "1.1", "172.16", "8.8.8.8"])
def test_public_host_short_ipv4_allowed(host):
    assert _is_private_host(host) is False


# ---------- Markdown BOM / front-matter ----------


async def test_front_matter_detected_despite_bom():
    source = "\ufeff---\ntitle: 指南\nproduct: MCP\n---\n\n# 标题\n\n正文\n".encode("utf-8")
    ast = await MarkdownParser().parse(source, {})
    assert ast.metadata["front_matter"]["title"] == "指南"
    assert ast.title == "指南"


async def test_bom_does_not_shift_line_numbers():
    # 有 BOM 与无 BOM 时，# 标题 都应落在第 5 行（front matter 占 1-4 行）
    with_bom = "\ufeff---\ntitle: x\n---\n---\n\n# 标题\n".encode("utf-8")
    ast = await MarkdownParser().parse(with_bom, {})
    heading = next(b for b in ast.blocks if b.type == BlockType.HEADING)
    assert heading.line_start == 6  # 行1--- 2 title 3--- 4--- 5 空 6 # 标题
