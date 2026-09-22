"""PDF 解析器：PDF 文档 -> DocumentAST（04 节 6-10）。

PDF 的结构信息远弱于 Markdown / HTML：没有可靠的标题层级与代码块。
本解析器按页抽取文本、按空行分段为 PARAGRAPH 块，
行号为页内累计序号（1 起始），heading_path 为空——
切分质量主要依赖段落聚合与 token 预算（04 节 15）。

依赖 pypdf（惰性导入）；未安装时以 FILE_UNSUPPORTED 失败，
不影响 Markdown / HTML 通路。
"""

import io

from app.core.errors import IngestionError, IngestionErrorCode
from app.core.versions import PDF_PARSER_VERSION
from app.domain.ingestion import ASTBlock, BlockType, DocumentAST


class PdfParser:
    name = "pdf"
    version = PDF_PARSER_VERSION

    async def parse(self, source: bytes, metadata: dict) -> DocumentAST:
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise IngestionError(
                IngestionErrorCode.FILE_UNSUPPORTED,
                "pdf support requires pypdf (pip install pypdf)",
                "PARSE",
            ) from exc
        if not source:
            raise IngestionError(IngestionErrorCode.FILE_EMPTY, "empty document", "PARSE")

        try:
            reader = PdfReader(io.BytesIO(source))
            pages = [(page.extract_text() or "") for page in reader.pages]
            pdf_meta_title = None
            if reader.metadata and reader.metadata.title:
                pdf_meta_title = str(reader.metadata.title).strip() or None
        except Exception as exc:
            raise IngestionError(
                IngestionErrorCode.PARSER_FAILED, f"pdf parse failed: {exc}", "PARSE"
            ) from exc

        text = "\n\n".join(p.strip() for p in pages if p.strip())
        if not text.strip():
            raise IngestionError(
                IngestionErrorCode.FILE_EMPTY, "no extractable text in pdf", "PARSE"
            )

        # 按空行分段；行号按全文累计
        blocks: list[ASTBlock] = []
        lineno = 1
        for chunk in text.split("\n\n"):
            lines = [ln.strip() for ln in chunk.splitlines() if ln.strip()]
            if not lines:
                continue
            blocks.append(
                ASTBlock(
                    type=BlockType.PARAGRAPH,
                    content="\n".join(lines),
                    heading_path=[],
                    line_start=lineno,
                    line_end=lineno + len(lines) - 1,
                )
            )
            lineno += len(lines)

        return DocumentAST(
            title=pdf_meta_title,
            metadata={"front_matter": {}, "explicit": dict(metadata)},
            blocks=blocks,
        )
