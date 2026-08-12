from __future__ import annotations

from dataclasses import dataclass

EXTRACTOR_VERSION = "phase10-v1"
FACT_DEFINITIONS = {
    "ownership_type": ("enum", frozenset({"independent", "family_owned", "employee_owned", "corporate", "cooperative", "nonprofit"})),
    "parent_organization": ("text", frozenset()),
    "founded_year": ("integer", frozenset()),
    "languages_offered": ("multi_text", frozenset()),
    "service_offering": ("enum", frozenset({"crematorium", "chapel", "reception_facilities", "pre_planning", "livestreaming", "grief_resources"})),
    "service_area": ("multi_text", frozenset()),
    "technology_signal": ("enum", frozenset({"online_arrangements"})),
}


@dataclass(frozen=True, slots=True)
class BusinessFactCandidate:
    fact_key: str
    value_kind: str
    raw_value: str
    normalized_value: str
    confidence: float
    extraction_method: str
    evidence_snippet: str
    scope: str
    scope_entity_id: int | None = None
