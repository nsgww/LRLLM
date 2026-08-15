"""Metadata resolution (04 sections 11-12).

Priority: explicit upload info > front matter > file name.
Conflicts must not be silently overwritten; they raise METADATA_CONFLICT.
"""

import re
from dataclasses import dataclass

from app.core.errors import IngestionError, IngestionErrorCode

_VERSION_RE = re.compile(r"^(?:v|version\s+)?(\d+(?:\.\d+){0,3})\s*$", re.IGNORECASE)

_FIELDS = ("title", "doc_class", "source", "product", "version")


@dataclass
class ResolvedMetadata:
    title: str | None = None
    doc_class: str | None = None
    source: str | None = None
    product: str | None = None
    version: str | None = None


def normalize_version(raw: str | None) -> str | None:
    """'v0.5.3' / 'version 0.5.3' -> '0.5.3' (04 section 12)."""
    if raw is None:
        return None
    match = _VERSION_RE.match(raw.strip())
    return match.group(1) if match else raw.strip()


def resolve_metadata(
    explicit: dict,
    front_matter: dict,
    filename: str | None = None,
) -> ResolvedMetadata:
    resolved = ResolvedMetadata()
    conflicts: list[str] = []

    for field_name in _FIELDS:
        explicit_value = _clean(explicit.get(field_name))
        fm_value = _clean(front_matter.get(field_name))
        value = explicit_value or fm_value

        if explicit_value and fm_value and explicit_value != fm_value:
            if field_name == "version" and normalize_version(explicit_value) == normalize_version(fm_value):
                pass  # same version in different notation is not a conflict
            else:
                conflicts.append(
                    f"{field_name}: explicit='{explicit_value}' front_matter='{fm_value}'"
                )

        if field_name == "title" and value is None and filename:
            value = filename.rsplit(".", 1)[0]
        setattr(resolved, field_name, value)

    resolved.version = normalize_version(resolved.version)

    if conflicts:
        raise IngestionError(
            IngestionErrorCode.METADATA_CONFLICT,
            "; ".join(conflicts),
            "METADATA",
        )
    return resolved


def _clean(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
