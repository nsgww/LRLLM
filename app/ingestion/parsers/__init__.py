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


def parser_for(content: str, hint: str | None = None) -> Parser:
    """按文件名提示 + 内容嗅探选择解析器。"""
    if hint:
        lowered = hint.lower()
        for suffix, kind in _HINT_SUFFIXES.items():
            if lowered.endswith(suffix):
                return _by_kind(kind)

    stripped = content.lstrip()
    if stripped.startswith("%PDF"):
        return PdfParser()
    sample = content[:2000].lower()
    if "<html" in sample or "<!doctype html" in sample:
        return HtmlParser()
    return MarkdownParser()


def _by_kind(kind: str) -> Parser:
    if kind == "html":
        return HtmlParser()
    if kind == "pdf":
        return PdfParser()
    return MarkdownParser()
