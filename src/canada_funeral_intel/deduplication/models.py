from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class EntityResolutionError(ValueError):
    """Raised when entity-resolution data is invalid."""


class EntityType(StrEnum):
    ORGANIZATION = "organization"
    BRANCH = "branch"


class MatchDecision(StrEnum):
    PENDING = "pending"
    MATCH = "match"
    NO_MATCH = "no_match"
    REVIEW = "review"


class EvidenceKind(StrEnum):
    DETERMINISTIC = "deterministic"
    FUZZY = "fuzzy"
    CONTEXT = "context"


@dataclass(frozen=True, slots=True)
class MatchEvidence:
    signal_name: str
    left_value: str | None
    right_value: str | None
    contribution: float
    evidence_kind: EvidenceKind

    def validate(self) -> None:
        if not self.signal_name.strip():
            raise EntityResolutionError("signal_name must not be empty")
        if not -1.0 <= self.contribution <= 1.0:
            raise EntityResolutionError("contribution must be between -1.0 and 1.0")


@dataclass(frozen=True, slots=True)
class MatchCandidate:
    left_source_record_id: int
    right_source_record_id: int
    candidate_method: str
    score: float
    decision: MatchDecision = MatchDecision.PENDING

    def validate(self) -> None:
        if self.left_source_record_id < 1:
            raise EntityResolutionError(
                "left_source_record_id must be a positive integer"
            )
        if self.right_source_record_id < 1:
            raise EntityResolutionError(
                "right_source_record_id must be a positive integer"
            )
        if self.left_source_record_id >= self.right_source_record_id:
            raise EntityResolutionError(
                "candidate source record IDs must be ordered and distinct"
            )
        if not self.candidate_method.strip():
            raise EntityResolutionError("candidate_method must not be empty")
        if not 0.0 <= self.score <= 1.0:
            raise EntityResolutionError("score must be between 0.0 and 1.0")


@dataclass(frozen=True, slots=True)
class MergeDecision:
    survivor_entity_id: int
    merged_entity_id: int
    decision_source: str
    reason: str

    def validate(self) -> None:
        if self.survivor_entity_id < 1 or self.merged_entity_id < 1:
            raise EntityResolutionError("entity IDs must be positive integers")
        if self.survivor_entity_id == self.merged_entity_id:
            raise EntityResolutionError("merge entity IDs must be distinct")
        if not self.decision_source.strip():
            raise EntityResolutionError("decision_source must not be empty")
        if not self.reason.strip():
            raise EntityResolutionError("reason must not be empty")
