"""入库边界测试：解析器与切分器的健壮性边界（无需数据库）。

覆盖：
- 未闭合代码围栏：到文件末尾仍捕获为一个 CODE_BLOCK，不丢内容、不崩。
- token_split：超长无标点/无换行的单段（评审 N8）必须终止且保留内容，
  不进入死循环、不产出空块；正常多句按句界切分。
"""

from app.domain.ingestion import BlockType
from app.ingestion.chunkers.token_split import TokenCounter, token_split
from app.ingestion.parsers.markdown import MarkdownParser


async def test_unterminated_code_fence_is_captured():
    # 围栏未闭合：应把到末尾的全部内容作为一个代码块，而不是丢弃或崩错
    source = b"# Doc\n\n```python\nline1\nline2\nline3"
    ast = await MarkdownParser().parse(source, {})
    code = next(b for b in ast.blocks if b.type == BlockType.CODE_BLOCK)
    assert code.content.startswith("```python")
    assert "line1" in code.content and "line3" in code.content


def test_token_split_oversized_single_line_terminates_and_preserves():
    counter = TokenCounter()
    giant = "a" * 200_000  # no spaces, no punctuation, no newlines
    result = token_split(giant, max_tokens=50, counter=counter)
    assert result, "must produce at least one piece"
    assert all(piece for piece in result), "no empty pieces"
    # 内容不丢：拼接后等于原文
    assert "".join(result) == giant


def test_token_split_splits_multi_sentence_text():
    counter = TokenCounter()
    text = ("这是第一句话。" * 200) + ("This is a sentence. " * 200)
    result = token_split(text, max_tokens=100, counter=counter)
    assert len(result) > 1
    assert all(piece.strip() for piece in result)
    # 词序完整保留（token_split 仅可能折叠纯空白片段，不丢内容）
    assert "".join(result).split() == text.split()


def test_token_split_short_text_returned_whole():
    counter = TokenCounter()
    assert token_split("短文本", max_tokens=512, counter=counter) == ["短文本"]
