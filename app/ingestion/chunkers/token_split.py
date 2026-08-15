"""Token counting and token-based splitting (04 section 15).

Token split is only a fallback for semantic units exceeding max tokens.
Split boundaries prefer paragraph -> line -> sentence, never mid-sentence
when avoidable. Code blocks are never split here (04 section 16).
"""

import re

_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[。！？.!?;；\n])")


class TokenCounter:
    """tiktoken with a graceful char-based fallback."""

    def __init__(self, encoding_name: str = "cl100k_base") -> None:
        self._enc = None
        try:
            import tiktoken

            self._enc = tiktoken.get_encoding(encoding_name)
        except Exception:
            self._enc = None

    def count(self, text: str) -> int:
        if self._enc is not None:
            return len(self._enc.encode(text))
        return max(1, len(text) // 4)


def token_split(text: str, max_tokens: int, counter: TokenCounter) -> list[str]:
    """Split oversized plain-text content at sentence boundaries."""
    if counter.count(text) <= max_tokens:
        return [text]
    pieces = [p for p in _SENTENCE_BOUNDARY_RE.split(text) if p.strip()]
    parts: list[str] = []
    current = ""
    for piece in pieces:
        candidate = current + piece
        if current and counter.count(candidate) > max_tokens:
            parts.append(current)
            current = piece
        else:
            current = candidate
    if current:
        parts.append(current)
    # a single sentence may still exceed the budget; hard-wrap by lines,
    # then accept the overlong piece rather than cutting mid-sentence
    result: list[str] = []
    for part in parts:
        if counter.count(part) <= max_tokens:
            result.append(part)
            continue
        line_parts = _split_by_lines(part, max_tokens, counter)
        result.extend(line_parts if line_parts else [part])
    return result


def _split_by_lines(text: str, max_tokens: int, counter: TokenCounter) -> list[str]:
    lines = text.splitlines()
    if len(lines) <= 1:
        return [text]
    parts: list[str] = []
    current = ""
    for line in lines:
        candidate = current + ("\n" if current else "") + line
        if current and counter.count(candidate) > max_tokens:
            parts.append(current)
            current = line
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts
