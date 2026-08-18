"""Context building (02-query-rag-spec sections 15-17, 06 section 8).

- Dedup by chunk_id.
- Version grouping with per-version cap when the user did not specify a
  version; boundaries are preserved in the final context text.
- Tables use raw_content for the final context (normalized text was for
  retrieval only).
- Everything is subject to the token budget; quality beats quantity.

Context expansion (parent section / neighbours) is intentionally minimal
in v0.1; heading path is always included with each chunk.
"""

from dataclasses import dataclass, field

from app.core.config import Settings
from app.domain.retrieval import RankedChunk
from app.ingestion.chunkers.token_split import TokenCounter


@dataclass
class BuiltContext:
    text: str = ""
    chunks: list[RankedChunk] = field(default_factory=list)
    token_count: int = 0


class ContextBuilder:
    def __init__(self, settings: Settings, counter: TokenCounter | None = None) -> None:
        self._settings = settings
        self._counter = counter or TokenCounter()

    def build(
        self,
        ranked: list[RankedChunk],
        version_specified: bool,
    ) -> BuiltContext:
        chunks = _dedup(ranked)
        if not version_specified:
            chunks = _apply_version_caps(chunks, self._settings.per_version_cap)

        context = BuiltContext()
        budget = self._settings.context_token_budget
        selected: list[RankedChunk] = []
        for chunk in chunks:
            text = chunk.raw_content or chunk.text
            cost = self._counter.count(text)
            if selected and context.token_count + cost > budget:
                continue
            selected.append(chunk)
            context.token_count += cost

        context.chunks = selected
        context.text = _format(selected, version_specified)
        return context


def _dedup(ranked: list[RankedChunk]) -> list[RankedChunk]:
    seen: set[str] = set()
    result = []
    for chunk in ranked:
        if chunk.chunk_id in seen:
            continue
        seen.add(chunk.chunk_id)
        result.append(chunk)
    return result


def _apply_version_caps(chunks: list[RankedChunk], cap: int) -> list[RankedChunk]:
    counts: dict[tuple[str | None, str | None], int] = {}
    result = []
    for chunk in chunks:
        key = (chunk.product, chunk.version)
        if counts.get(key, 0) >= cap:
            continue
        counts[key] = counts.get(key, 0) + 1
        result.append(chunk)
    return result


def _format(chunks: list[RankedChunk], version_specified: bool) -> str:
    groups: dict[tuple[str | None, str | None], list[RankedChunk]] = {}
    order: list[tuple[str | None, str | None]] = []
    for chunk in chunks:
        key = (chunk.product, chunk.version)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(chunk)

    multiple_groups = len(order) > 1
    parts: list[str] = []
    for key in order:
        product, version = key
        if not version_specified and multiple_groups:
            label = " ".join(p for p in (product, f"v{version}" if version else None) if p)
            parts.append(f"=== {label or 'unknown version'} ===")
        for chunk in groups[key]:
            body = chunk.raw_content or chunk.text
            parts.append(f"[{chunk.heading_path}]\n{body}")
    return "\n\n".join(parts)
