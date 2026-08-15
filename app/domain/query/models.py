"""Query domain models (02-query-rag-spec sections 2/3/5)."""

from dataclasses import dataclass, field
from enum import Enum


class Intent(str, Enum):
    EXACT_QA = "exact_qa"
    HOW_TO = "how_to"
    SUMMARY = "summary"
    COMPARISON = "comparison"
    CAPABILITY = "capability"
    CONCEPT = "concept"
    DOCUMENT_ANALYSIS = "document_analysis"
    GENERAL_KNOWLEDGE = "general_knowledge"
    TOOL_ACTION = "tool_action"


@dataclass
class QueryUnderstanding:
    intent: Intent
    knowledge_required: bool
    product: str | None = None
    version: str | None = None
    entities: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)


@dataclass
class SubQuery:
    id: str
    query: str
    product: str | None = None
    version: str | None = None
