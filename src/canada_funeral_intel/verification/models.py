from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class WebsiteDiscoveryError(ValueError):
    """Raised when website-discovery data is invalid."""


class WebsiteKind(StrEnum):
    CANDIDATE = "candidate"
    OFFICIAL = "official"
    BRANCH = "branch"
    SHARED = "shared"
    ALTERNATE = "alternate"
    SOCIAL = "social"


class WebsiteStatus(StrEnum):
    CANDIDATE = "candidate"
    REVIEW = "review"
    SELECTED = "selected"
    REJECTED = "rejected"


class WebsiteEvidenceType(StrEnum):
    SOURCE_URL = "source_url"
    NORMALIZED_URL = "normalized_url"
    DOMAIN = "domain"
    BUSINESS_NAME = "business_name"
    LOCATION = "location"
    PARENT_ORGANIZATION = "parent_organization"
    MANUAL = "manual"


class WebsiteEvidenceClass(StrEnum):
    EXPLICIT_SOURCE_WEBSITE = "explicit_source_website"
    EXPLICIT_SOURCE_URL = "explicit_source_url"
    SOURCE_DOMAIN = "source_domain"
    NORMALIZED_URL = "normalized_url"
    NORMALIZED_DOMAIN = "normalized_domain"
    EMAIL_DOMAIN = "email_domain"
    MANUAL = "manual"


class WebsiteReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DEFERRED = "deferred"


@dataclass(frozen=True, slots=True)
class WebsiteCandidate:
    entity_id: int
    url: str
    normalized_url: str
    domain: str
    discovery_method: str
    confidence: float
    website_kind: WebsiteKind = WebsiteKind.CANDIDATE
    status: WebsiteStatus = WebsiteStatus.CANDIDATE
    source_record_id: int | None = None
    is_primary: bool = False

    def validate(self) -> None:
        if self.entity_id < 1:
            raise WebsiteDiscoveryError("entity_id must be a positive integer")
        if self.source_record_id is not None and self.source_record_id < 1:
            raise WebsiteDiscoveryError(
                "source_record_id must be a positive integer when provided"
            )
        for label, value in (
            ("url", self.url),
            ("normalized_url", self.normalized_url),
            ("domain", self.domain),
            ("discovery_method", self.discovery_method),
        ):
            if not value.strip():
                raise WebsiteDiscoveryError(f"{label} must not be empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise WebsiteDiscoveryError("confidence must be between 0.0 and 1.0")
        if self.website_kind is WebsiteKind.SOCIAL and self.is_primary:
            raise WebsiteDiscoveryError(
                "social profiles cannot be selected as primary websites automatically"
            )
        if self.is_primary and self.status is not WebsiteStatus.SELECTED:
            raise WebsiteDiscoveryError("primary websites must have selected status")


@dataclass(frozen=True, slots=True)
class WebsiteEvidence:
    evidence_type: WebsiteEvidenceType
    contribution: float
    evidence_value: str | None = None
    source_record_id: int | None = None
    normalized_value_id: int | None = None
    evidence_class: WebsiteEvidenceClass | None = None
    derivation_method: str = "website-candidate-evidence-v1"
    derivation_version: str = "website-candidate-evidence-v1"
    raw_value: str | None = None

    def validate(self) -> None:
        if self.source_record_id is not None and self.source_record_id < 1:
            raise WebsiteDiscoveryError(
                "source_record_id must be a positive integer when provided"
            )
        if self.normalized_value_id is not None and self.normalized_value_id < 1:
            raise WebsiteDiscoveryError(
                "normalized_value_id must be positive when provided"
            )
        if not -1.0 <= self.contribution <= 1.0:
            raise WebsiteDiscoveryError("contribution must be between -1.0 and 1.0")
        if self.evidence_value is not None and not self.evidence_value.strip():
            raise WebsiteDiscoveryError(
                "evidence_value must not be blank when provided"
            )
        if not self.derivation_method.strip() or not self.derivation_version.strip():
            raise WebsiteDiscoveryError(
                "evidence derivation metadata must not be blank"
            )


@dataclass(frozen=True, slots=True)
class WebsiteRecord:
    website_id: int
    entity_id: int
    source_record_id: int | None
    url: str
    normalized_url: str
    domain: str
    website_kind: WebsiteKind
    discovery_method: str
    confidence: float
    status: WebsiteStatus
    is_primary: bool
