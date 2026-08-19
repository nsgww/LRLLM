"""Metadata resolution contract tests (04 sections 11-12)."""

import pytest

from app.core.errors import IngestionError
from app.ingestion.metadata import normalize_version, resolve_metadata


def test_explicit_and_front_matter_merge_by_field():
    resolved = resolve_metadata({"title": "Upload Title"}, {"product": "MCP"})
    assert resolved.title == "Upload Title"
    assert resolved.product == "MCP"


def test_conflicting_values_raise_metadata_conflict():
    with pytest.raises(IngestionError) as exc_info:
        resolve_metadata({"product": "A"}, {"product": "B"})
    assert exc_info.value.code == "METADATA_CONFLICT"
    assert exc_info.value.stage == "METADATA"


def test_version_notation_difference_is_not_a_conflict():
    resolved = resolve_metadata({"version": "v0.5.3"}, {"version": "0.5.3"})
    assert resolved.version == "0.5.3"


def test_version_normalization():
    assert normalize_version("v0.5.3") == "0.5.3"
    assert normalize_version("version 0.6.0") == "0.6.0"
    assert normalize_version(" 1.2 ") == "1.2"
    assert normalize_version("latest") == "latest"
    assert normalize_version(None) is None


def test_title_falls_back_to_filename():
    resolved = resolve_metadata({}, {}, filename="install-guide.md")
    assert resolved.title == "install-guide"


def test_blank_values_treated_as_missing():
    resolved = resolve_metadata({"product": "  "}, {"product": "MCP"})
    assert resolved.product == "MCP"
