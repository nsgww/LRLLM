"""Markdown 解析器：原始 Markdown → 文档抽象语法树（DocumentAST）（第 04 节 6-10）。

- 保留每个代码块的 heading_path 以及以 1 为起点的行范围。
- 代码围栏保留其原始文本（包括围栏本身），因此代码块保持
  完整的语义单元。
- 前置信息被收集为元数据；与显式
  上传元数据的冲突解决在 app/ingestion/metadata.py 中进行，而非在此处。
"""

import re

from app.core.errors import IngestionError, IngestionErrorCode
from app.core.versions import PARSER_VERSION
from app.domain.ingestion import ASTBlock, BlockType, DocumentAST

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_FENCE_RE = re.compile(r"^```")
_LIST_ITEM_RE = re.compile(r"^(\s*)([-*+]|\d+\.)\s+")
_QUOTE_RE = re.compile(r"^>\s?")
_TABLE_ROW_RE = re.compile(r"^\|.*\|\s*$")


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
    """Minimal 'key: value' parsing; no full YAML dependency in v0.1."""
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

        if _FENCE_RE.match(line):
            j = i + 1
            while j < n and not _FENCE_RE.match(lines[j]):
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
