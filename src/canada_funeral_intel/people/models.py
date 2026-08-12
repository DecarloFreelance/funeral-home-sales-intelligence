from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PersonResolutionError(RuntimeError):
    """Raised when person resolution cannot complete safely."""


class PersonStatus(StrEnum):
    ACTIVE = "active"
    MERGED = "merged"
    INACTIVE = "inactive"


class PersonReviewStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DEFERRED = "deferred"


class PersonReasonCode(StrEnum):
    EXACT_EMAIL_SAME_ENTITY = "exact_email_same_entity"
    EXACT_PHONE_COMPATIBLE_NAME = "exact_phone_compatible_name"
    EXACT_NAME_ROLE_SAME_ENTITY = "exact_name_role_same_entity"
    REPEATED_CONTACT_ACROSS_PAGES = "repeated_contact_across_pages"
    CONFLICTING_EMAIL = "conflicting_email"
    CONFLICTING_PHONE = "conflicting_phone"
    CROSS_BRANCH_AMBIGUOUS = "cross_branch_ambiguous"


@dataclass(frozen=True, slots=True)
class PersonRecord:
    person_id: int
    canonical_name: str
    normalized_name: str
    status: PersonStatus


@dataclass(frozen=True, slots=True)
class PersonCandidateRecord:
    candidate_id: int
    left_observation_id: int
    right_observation_id: int
    score: float
    reason_code: PersonReasonCode
    status: PersonReviewStatus
    priority: int
    queue_id: int | None


@dataclass(frozen=True, slots=True)
class PersonMergeDecision:
    survivor_person_id: int
    merged_person_id: int
    decision_source: str
    reason: str

    def validate(self) -> None:
        if self.survivor_person_id < 1 or self.merged_person_id < 1:
            raise PersonResolutionError("person IDs must be positive")
        if self.survivor_person_id == self.merged_person_id:
            raise PersonResolutionError("person merge IDs must be distinct")
        if not self.decision_source.strip() or not self.reason.strip():
            raise PersonResolutionError("person merge source and reason are required")
