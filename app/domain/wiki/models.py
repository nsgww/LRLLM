"""Wiki domain models (11-llm-wiki-spec section 3).

Pure dataclasses / enums, zero framework or database dependencies
(see app/domain/__init__.py). The wiki is a derived knowledge layer distilled
from query traces; every revision keeps a source reference for grounding.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class WikiStatus(str, Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class WikiSourceType(str, Enum):
    """Marks whether a document/chunk row is an original doc or a wiki page."""

    DOCUMENT = "document"
    WIKI = "wiki"


@dataclass
class WikiSourceRef:
    """Where a revision's knowledge came from (grounding / traceability)."""

    answer_id: str | None = None
    query: str = ""
    # Snapshot of the answer's selected_chunks:
    # [{document_id, chunk_id, version, heading_path, line_start, line_end}]
    evidence: list[dict] = field(default_factory=list)


@dataclass
class WikiPage:
    knowledge_base_id: str
    slug: str
    title: str
    summary: str = ""
    status: WikiStatus = WikiStatus.PUBLISHED
    revision_count: int = 0
    id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class WikiRevision:
    page_id: str
    version: int
    content: str
    source: WikiSourceRef = field(default_factory=WikiSourceRef)
    change_note: str = ""
    status: WikiStatus = WikiStatus.PUBLISHED
    id: str | None = None
    created_at: datetime | None = None
