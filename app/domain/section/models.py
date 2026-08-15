"""Section domain model (04-ingestion-pipeline-spec section 13)."""

from dataclasses import dataclass


@dataclass
class Section:
    document_id: str
    heading: str
    heading_path: str
    level: int
    section_order: int
    line_start: int
    line_end: int
    id: str | None = None
    parent_section_id: str | None = None
