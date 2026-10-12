"""Parsers. All parsers must output the unified DocumentAST (04 section 8).

parser_for 按文件名提示 + 内容嗅探选择解析器（04 节 23）：
- 提示命中已知扩展名时优先
- PDF 以 %PDF 魔数识别；含 HTML 标签的按 HTML 处理
- 其余一律按 Markdown 处理（纯文本兼容）
"""

from app.ingestion.parsers.base import Parser
from app.ingestion.parsers.html import HtmlParser
from app.ingestion.parsers.markdown import MarkdownParser
from app.ingestion.parsers.pdf import PdfParser

__all__ = ["Parser", "parser_for"]

_HINT_SUFFIXES = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".html": "html",
    ".htm": "html",
    ".pdf": "pdf",
}


def parser_for(content: bytes, hint: str | None = None) -> Parser:
    """按文件名提示 + 内容嗅探选择解析器。

    ``content`` 为原始字节（BYTEA）。嗅探只对 ASCII 前缀做判断，故以
    latin-1 容错解码出前 2KB 再匹配魔数/标签，二进制字节不会让嗅探崩溃。
    """
    if hint:
        lowered = hint.lower()
        for suffix, kind in _HINT_SUFFIXES.items():
            if lowered.endswith(suffix):
                return _by_kind(kind)

    prefix = content[:2048].decode("latin-1", errors="ignore")
    stripped = prefix.lstrip()
    if stripped.startswith("%PDF"):
        return PdfParser()
    sample = prefix.lower()
    if "<html" in sample or "<!doctype html" in sample:
        return HtmlParser()
    return MarkdownParser()


def _by_kind(kind: str) -> Parser:
    if kind == "html":
        return HtmlParser()
    if kind == "pdf":
        return PdfParser()
    return MarkdownParser()
