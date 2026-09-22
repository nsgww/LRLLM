"""HTML 解析器：HTML 文档 -> DocumentAST（04 节 6-10）。

仅依赖标准库 html.parser，输出与 Markdown 解析器统一的块模型：
- h1-h6 -> HEADING（维护 heading_path 标题栈）
- pre -> CODE_BLOCK（原样保留）
- table -> TABLE（渲染为 Markdown 表格，走同一套表格切块逻辑）
- ul/ol -> LIST，li -> LIST_ITEM
- blockquote -> QUOTE，p 及游离文本 -> PARAGRAPH
- script/style 内容丢弃
行号取自 HTML 源码中的位置（1 起始），与 Markdown 口径一致。
"""

from html.parser import HTMLParser

from app.core.errors import IngestionError, IngestionErrorCode
from app.core.versions import HTML_PARSER_VERSION
from app.domain.ingestion import ASTBlock, BlockType, DocumentAST

_HEADING_TAGS = {f"h{i}": i for i in range(1, 7)}
_SKIP_TAGS = {"script", "style"}


class HtmlParser:
    name = "html"
    version = HTML_PARSER_VERSION

    async def parse(self, source: bytes, metadata: dict) -> DocumentAST:
        try:
            text = source.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise IngestionError(
                IngestionErrorCode.FILE_INVALID, f"not valid utf-8: {exc}", "PARSE"
            ) from exc
        if not text.strip():
            raise IngestionError(IngestionErrorCode.FILE_EMPTY, "empty document", "PARSE")

        extractor = _BlockExtractor()
        extractor.feed(text)
        extractor.close()
        if not extractor.blocks:
            raise IngestionError(
                IngestionErrorCode.PARSER_FAILED, "no content blocks extracted", "PARSE"
            )

        title = extractor.title or _first_heading(extractor.blocks)
        return DocumentAST(
            title=title,
            metadata={"front_matter": {}, "explicit": dict(metadata)},
            blocks=extractor.blocks,
        )


def _first_heading(blocks: list[ASTBlock]) -> str | None:
    for block in blocks:
        if block.type == BlockType.HEADING:
            return block.content
    return None


class _BlockExtractor(HTMLParser):
    """流式遍历 HTML，把块级元素转换为 ASTBlock。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[ASTBlock] = []
        self.title: str | None = None
        self._heading_stack: list[tuple[int, str]] = []
        self._skip_depth = 0
        self._current: dict | None = None  # 正在收集的块
        self._table: dict | None = None    # 正在收集的表格
        self._cell: list[str] | None = None

    # ---- 工具 ----

    def _line(self) -> int:
        return self.getpos()[0]

    def _path(self) -> list[str]:
        return [t for _, t in self._heading_stack]

    def _emit_current(self) -> None:
        cur = self._current
        if cur is None:
            return
        self._current = None
        content = "\n".join(cur["lines"]).strip()
        if not content:
            return
        self.blocks.append(
            ASTBlock(
                type=cur["type"],
                content=content,
                level=cur.get("level"),
                heading_path=self._path() if cur["type"] != BlockType.HEADING else cur["path"],
                line_start=cur["line_start"],
                line_end=self._line(),
                children=cur.get("children", []),
            )
        )

    def _start_block(self, block_type: BlockType, level: int | None = None) -> None:
        self._emit_current()
        self._current = {"type": block_type, "lines": [], "line_start": self._line(), "level": level}

    # ---- 标签处理 ----

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return

        if tag in _HEADING_TAGS:
            self._start_block(BlockType.HEADING, level=_HEADING_TAGS[tag])
            self._current["path"] = []
        elif tag == "pre":
            self._start_block(BlockType.CODE_BLOCK)
        elif tag == "p":
            self._start_block(BlockType.PARAGRAPH)
        elif tag == "blockquote":
            self._start_block(BlockType.QUOTE)
        elif tag in ("ul", "ol"):
            self._start_block(BlockType.LIST)
            self._current["children"] = []
        elif tag == "li":
            if self._current is None or self._current["type"] != BlockType.LIST:
                self._start_block(BlockType.LIST)
                self._current["children"] = []
            self._current["lines"].append("")  # 新列表项占位
        elif tag == "table":
            self._emit_current()
            self._table = {"rows": [], "line_start": self._line()}
        elif tag == "tr" and self._table is not None:
            self._table["rows"].append([])
        elif tag in ("td", "th") and self._table is not None:
            self._cell = []
        elif tag == "br":
            self._append_text("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return

        if tag in _HEADING_TAGS and self._current is not None:
            level = self._current.get("level") or 1
            title = "\n".join(self._current["lines"]).strip()
            self._current = None
            if not title:
                return
            while self._heading_stack and self._heading_stack[-1][0] >= level:
                self._heading_stack.pop()
            self._heading_stack.append((level, title))
            self.blocks.append(
                ASTBlock(
                    type=BlockType.HEADING,
                    content=title,
                    level=level,
                    heading_path=self._path(),
                    line_start=self._line(),
                    line_end=self._line(),
                )
            )
        elif tag in ("pre", "p", "blockquote", "ul", "ol"):
            self._emit_current()
        elif tag in ("td", "th") and self._cell is not None and self._table is not None:
            cell_text = "".join(self._cell).strip()
            self._cell = None
            if self._table["rows"]:
                self._table["rows"][-1].append(cell_text)
        elif tag == "table" and self._table is not None:
            table = self._table
            self._table = None
            lines = ["| " + " | ".join(row) + " |" for row in table["rows"] if row]
            if lines:
                self.blocks.append(
                    ASTBlock(
                        type=BlockType.TABLE,
                        content="\n".join(lines),
                        heading_path=self._path(),
                        line_start=table["line_start"],
                        line_end=self._line(),
                    )
                )

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._cell is not None:
            self._cell.append(data)
            return
        if self._table is not None:
            return  # 表格结构外的文本丢弃
        if self._current is None:
            if not data.strip():
                return
            self._start_block(BlockType.PARAGRAPH)  # 游离文本按段落处理
        self._append_text(data)

    def _append_text(self, data: str) -> None:
        cur = self._current
        if cur is None:
            return
        if cur["type"] == BlockType.LIST:
            if not cur["lines"]:
                cur["lines"].append("")
            cur["lines"][-1] += data
        elif cur["type"] == BlockType.CODE_BLOCK:
            cur["lines"].append(data.rstrip("\r"))
        else:
            cur["lines"].append(data)
