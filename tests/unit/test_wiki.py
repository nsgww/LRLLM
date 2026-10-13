"""LLM Wiki unit tests (11-llm-wiki-spec).

Pure logic only — no database / Qdrant / LLM. Covers the extraction schema,
distill gating, metadata-filter passthrough, and the Qdrant wiki exclusion.
"""

import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.domain.retrieval import MetadataFilter
from app.llm.schemas import WikiExtractionOutput
from app.retrieval.filters import build_metadata_filter
from app.services.wiki_service import (
    WikiService,
    _estimate_tokens,
    _evidence_list,
    _evidence_text,
    _normalize_slug,
)
from app.storage.qdrant.store import QdrantVectorStore


def test_wiki_extraction_output_defaults():
    out = WikiExtractionOutput()
    assert out.should_create is False
    assert out.slug == "" and out.tags == []


def test_normalize_slug():
    assert _normalize_slug("  My-Topic ") == "my-topic"


def test_evidence_helpers():
    assert _evidence_text(None) == "（无）"
    lst = [{"document_id": "d", "chunk_id": "c"}]
    assert _evidence_list(lst) == lst
    assert _evidence_list({"chunks": lst}) == lst
    assert _evidence_list("x") == []
    assert "document_id" in _evidence_text(lst)


def test_estimate_tokens_positive():
    assert _estimate_tokens("") >= 1
    assert _estimate_tokens("abcd" * 100) > 1


def test_metadata_filter_default_includes_wiki():
    assert MetadataFilter(knowledge_base_id="kb").include_wiki is True


def test_build_metadata_filter_passes_include_wiki():
    assert build_metadata_filter("kb", include_wiki=False).include_wiki is False
    assert build_metadata_filter("kb").include_wiki is True


def test_qdrant_filter_excludes_wiki_when_disabled():
    flt = QdrantVectorStore._build_filter(
        MetadataFilter(knowledge_base_id="kb", include_wiki=False)
    )
    excluded = [c.match.value for c in flt.must_not]
    assert "wiki" in excluded


def test_qdrant_filter_default_has_no_wiki_exclusion():
    flt = QdrantVectorStore._build_filter(MetadataFilter(knowledge_base_id="kb"))
    assert list(flt.must_not) == []


async def test_distill_disabled_raises_503():
    svc = WikiService(
        None,
        llm=None,
        prompts=None,
        vector_store=None,
        embedding=None,
        settings=Settings(wiki_enabled=False),
    )
    with pytest.raises(AppError) as ei:
        await svc.distill("00000000-0000-0000-0000-000000000000")
    assert ei.value.code == "WIKI_DISABLED"
    assert ei.value.http_status == 503


def test_qdrant_filter_with_version_targets_version_only():
    # 指定 version 时 filter 命中 version='0.5.3'；wiki 检索块 version=None
    # 不匹配该条件 → 指定版本下 wiki 自动被排除（零跨版本，符合 06）。
    flt = QdrantVectorStore._build_filter(
        MetadataFilter(knowledge_base_id="kb", version="0.5.3")
    )
    version_values = [c.match.value for c in flt.must if c.key == "version"]
    assert version_values == ["0.5.3"]


def test_qdrant_filter_without_version_lets_wiki_participate():
    # 未指定 version 时无 version 条件，wiki 块（version=None）可参与召回。
    flt = QdrantVectorStore._build_filter(MetadataFilter(knowledge_base_id="kb"))
    assert [c.key for c in flt.must] == ["knowledge_base_id"]


def test_wiki_extraction_prompt_vars_match_service_contract():
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    content = (root / "app/llm/prompts/seed/wiki_extraction.md").read_text(encoding="utf-8")
    vars_ = sorted(set(re.findall(r"{{(\w+)}}", content)))
    assert vars_ == sorted(
        ["source_query", "final_answer", "evidence", "existing_content", "max_content_tokens"]
    )
