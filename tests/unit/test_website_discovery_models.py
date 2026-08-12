from __future__ import annotations

import pytest

from canada_funeral_intel.verification.models import (
    WebsiteCandidate,
    WebsiteDiscoveryError,
    WebsiteEvidence,
    WebsiteEvidenceType,
    WebsiteKind,
    WebsiteStatus,
)
from canada_funeral_intel.verification.storage import make_website_candidate


def test_make_candidate_normalizes_url_and_domain() -> None:
    candidate = make_website_candidate(
        entity_id=1,
        url="Example.CA/contact#staff",
        discovery_method="source_record_url",
        confidence=0.72,
    )

    assert candidate.normalized_url == "https://example.ca/contact"
    assert candidate.domain == "example.ca"


def test_social_candidate_cannot_be_primary_automatically() -> None:
    candidate = WebsiteCandidate(
        entity_id=1,
        url="https://social.example/profile",
        normalized_url="https://social.example/profile",
        domain="social.example",
        discovery_method="manual",
        confidence=0.5,
        website_kind=WebsiteKind.SOCIAL,
        status=WebsiteStatus.SELECTED,
        is_primary=True,
    )

    with pytest.raises(WebsiteDiscoveryError, match="social profiles"):
        candidate.validate()


def test_primary_candidate_requires_selected_status() -> None:
    candidate = WebsiteCandidate(
        entity_id=1,
        url="https://example.ca/",
        normalized_url="https://example.ca/",
        domain="example.ca",
        discovery_method="manual",
        confidence=0.9,
        is_primary=True,
    )

    with pytest.raises(WebsiteDiscoveryError, match="selected status"):
        candidate.validate()


def test_evidence_contribution_is_bounded() -> None:
    evidence = WebsiteEvidence(
        evidence_type=WebsiteEvidenceType.DOMAIN,
        evidence_value="example.ca",
        contribution=1.1,
    )

    with pytest.raises(WebsiteDiscoveryError, match="between -1.0 and 1.0"):
        evidence.validate()
