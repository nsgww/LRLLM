"""Markdown 解析器：原始 Markdown → 文档抽象语法树（DocumentAST）（第 04 节 6-10）。

- 保留每个代码块的 heading_path 以及以 1 为起点的行范围。
- 代码围栏保留其原始文本（包括围栏本身），因此代码块保持
  完整的语义单元。
- 前置信息被收集为元数据；与显式
  上传元数据的冲突解决在 app/ingestion/metadata.py 中进行，而非在此处。
"""

import logging
import re

from app.core.errors import IngestionError, IngestionErrorCode
from app.core.versions import PARSER_VERSION
from app.domain.ingestion import ASTBlock, BlockType, DocumentAST

logger = logging.getLogger(__name__)

try:
    import yaml
except ImportError:  # pragma: no cover - yaml is a declared dependency
    yaml = None

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_FENCE_RE = re.compile(r"^(`{3,}|~{3,})")
_LIST_ITEM_RE = re.compile(r"^(\s*)([-*+]|\d+\.)\s+")
_QUOTE_RE = re.compile(r"^>\s?")
_TABLE_ROW_RE = re.compile(r"^\|.*\|\s*$")
_INDENTED_CODE_RE = re.compile(r"^(?: {4,}|\t)")


def _fence_char(line: str) -> str | None:
    """Return the fence character (`` ` `` or ``~``) opening a code fence."""
    match = _FENCE_RE.match(line)
    return match.group(1)[0] if match else None


def _dedent_code(line: str) -> str:
    """Strip one level of indentation (a tab or up to four spaces)."""
    if line.startswith("\t"):
        return line[1:]
    return line[4:] if line.startswith("    ") else line.lstrip(" ")


class MarkdownParser:
    name = "markdown"
    version = PARSER_VERSION

    async def parse(self, source: bytes, metadata: dict) -> DocumentAST:
        try:
            text = source.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise IngestionError(
                IngestionErrorCode.FILE_INVALID, f"not valid utf-8: {exc}", "PARSE"
            ) from exc
        # A leading UTF-8 BOM would otherwise make the first line "\ufeff---",
        # which never equals "---", silently disabling front-matter detection.
        text = text.removeprefix("\ufeff")
        if not text.strip():
            raise IngestionError(IngestionErrorCode.FILE_EMPTY, "empty document", "PARSE")

        front_matter, body, body_start_line = _extract_front_matter(text)
        blocks = _parse_blocks(body.splitlines(), body_start_line)
        title = front_matter.get("title") or _first_heading(blocks)
        return DocumentAST(
            title=title,
            metadata={"front_matter": front_matter, "explicit": dict(metadata)},
            blocks=blocks,
        )


def _extract_front_matter(text: str) -> tuple[dict, str, int]:
    """Returns (front_matter, body, body_start_line). body_start_line is the
    1-based line number of the first body line in the original document."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text, 1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            fm = _parse_front_matter(lines[1:i])
            return fm, "\n".join(lines[i + 1 :]), i + 2
    return {}, text, 1


def _parse_front_matter(lines: list[str]) -> dict:
    """Front matter parsed as YAML (scalars, lists and nested maps).

    Falls back to a minimal ``key: value`` parse when YAML is unavailable or
    the block is malformed, so ingestion never fails on a bad header.
    """
    raw = "\n".join(lines)
    if yaml is not None:
        try:
            parsed = yaml.safe_load(raw)
            if isinstance(parsed, dict):
                return {str(key): value for key, value in parsed.items() if value is not None}
            return {}
        except Exception:
            # 刻意降级：畸形 front matter 不应让整个入库失败。但留一条
            # debug 日志，避免系统性的 YAML 问题被完全吞掉、无从排查。
            logger.debug("front matter YAML parse failed; using simple fallback", exc_info=True)
    return _parse_front_matter_simple(lines)


def _parse_front_matter_simple(lines: list[str]) -> dict:
    """Minimal 'key: value' parsing kept as a no-dependency fallback."""
    data: dict = {}
    for line in lines:
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            data[key] = value
    return data


def _first_heading(blocks: list[ASTBlock]) -> str | None:
    for block in blocks:
        if block.type == BlockType.HEADING:
            return block.content
    return None


def _parse_blocks(lines: list[str], start_line: int) -> list[ASTBlock]:
    blocks: list[ASTBlock] = []
    heading_stack: list[tuple[int, str]] = []
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        lineno = start_line + i

        if not line.strip():
            i += 1
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            title = heading.group(2)
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, title))
            path = [t for _, t in heading_stack]
            blocks.append(
                ASTBlock(
                    type=BlockType.HEADING,
                    content=title,
                    level=level,
                    heading_path=path,
                    line_start=lineno,
                    line_end=lineno,
                )
            )
            i += 1
            continue

        path = [t for _, t in heading_stack]

        opening_char = _fence_char(line)
        if opening_char:
            j = i + 1
            # The closing fence must use the same character as the opening one
            # (`` ``` `` fences do not close `` ~~~ `` blocks and vice versa).
            while j < n and _fence_char(lines[j]) != opening_char:
                j += 1
            end = j if j < n else n - 1  # include closing fence when present
            content = "\n".join(lines[i : end + 1])
            blocks.append(
                ASTBlock(
                    type=BlockType.CODE_BLOCK,
                    content=content,
                    heading_path=path,
                    line_start=lineno,
                    line_end=start_line + end,
                )
            )
            i = end + 1
            continue

        if _TABLE_ROW_RE.match(line):
            j = i
            while j < n and _TABLE_ROW_RE.match(lines[j]):
                j += 1
            blocks.append(
                ASTBlock(
                    type=BlockType.TABLE,
                    content="\n".join(lines[i:j]),
                    heading_path=path,
                    line_start=lineno,
                    line_end=start_line + j - 1,
                )
            )
            i = j
            continue

        # Indented code block: a run of lines indented by >= 4 spaces (or a
        # tab) that is not a list item. Nested list items are handled by the
        # list branch below, and continuation lines already belong to a list,
        # so this only matches block starts (04 section 6).
        if _INDENTED_CODE_RE.match(line) and not _LIST_ITEM_RE.match(line):
            last = i
            j = i
            while j < n and (not lines[j].strip() or _INDENTED_CODE_RE.match(lines[j])):
                if lines[j].strip():
                    last = j
                j += 1
            blocks.append(
                ASTBlock(
                    type=BlockType.CODE_BLOCK,
                    content="\n".join(_dedent_code(lines[k]) for k in range(i, last + 1)),
                    heading_path=path,
                    line_start=lineno,
                    line_end=start_line + last,
                )
            )
            i = last + 1
            continue

        if _LIST_ITEM_RE.match(line):
            j = i
            items = []
            while j < n and (lines[j].strip() and (_LIST_ITEM_RE.match(lines[j]) or lines[j].startswith((" ", "\t")))):
                if _LIST_ITEM_RE.match(lines[j]):
                    items.append(lines[j])
                j += 1
            blocks.append(
                ASTBlock(
                    type=BlockType.LIST,
                    content="\n".join(lines[i:j]),
                    heading_path=path,
                    line_start=lineno,
                    line_end=start_line + j - 1,
                    children=[
                        ASTBlock(
                            type=BlockType.LIST_ITEM,
                            content=item.strip(),
                            heading_path=path,
                            line_start=lineno,
                            line_end=lineno,
                        )
                        for item in items
                    ],
                )
            )
            i = j
            continue

        if _QUOTE_RE.match(line):
            j = i
            while j < n and _QUOTE_RE.match(lines[j]):
                j += 1
            blocks.append(
                ASTBlock(
                    type=BlockType.QUOTE,
                    content="\n".join(lines[i:j]),
                    heading_path=path,
                    line_start=lineno,
                    line_end=start_line + j - 1,
                )
            )
            i = j
            continue

        # paragraph: consecutive non-empty, non-special lines
        j = i
        while j < n and lines[j].strip():
            if j > i and (
                _HEADING_RE.match(lines[j])
                or _FENCE_RE.match(lines[j])
                or _TABLE_ROW_RE.match(lines[j])
                or _LIST_ITEM_RE.match(lines[j])
                or _QUOTE_RE.match(lines[j])
            ):
                break
            j += 1
        blocks.append(
            ASTBlock(
                type=BlockType.PARAGRAPH,
                content="\n".join(lines[i:j]),
                heading_path=path,
                line_start=lineno,
                line_end=start_line + j - 1,
            )
        )
        i = j

    return blocks
