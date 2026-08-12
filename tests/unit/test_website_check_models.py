from __future__ import annotations

import pytest

from canada_funeral_intel.verification.checks import (
    DNSStatus,
    TLSStatus,
    WebsiteCheck,
    WebsiteCheckError,
    WebsiteCheckOutcome,
)


def test_website_check_accepts_complete_result() -> None:
    check = WebsiteCheck(
        website_id=1,
        requested_url="https://example.ca/",
        final_url="https://www.example.ca/",
        dns_status=DNSStatus.OK,
        dns_addresses=("192.0.2.10", "2001:db8::10"),
        tls_status=TLSStatus.OK,
        tls_expires_at="2027-01-01T00:00:00Z",
        https_status_code=200,
        http_status_code=301,
        redirect_count=1,
        response_time_ms=125,
        content_type="text/html",
        canonical_url="https://www.example.ca/",
        identity_score=0.92,
        outcome=WebsiteCheckOutcome.REACHABLE,
    )

    check.validate()


def test_website_check_rejects_invalid_status_code() -> None:
    check = WebsiteCheck(
        website_id=1,
        requested_url="https://example.ca/",
        https_status_code=700,
    )

    with pytest.raises(
        WebsiteCheckError,
        match="https_status_code",
    ):
        check.validate()


def test_website_check_rejects_invalid_identity_score() -> None:
    check = WebsiteCheck(
        website_id=1,
        requested_url="https://example.ca/",
        identity_score=1.01,
    )

    with pytest.raises(
        WebsiteCheckError,
        match="identity_score",
    ):
        check.validate()


def test_website_check_rejects_negative_redirect_count() -> None:
    check = WebsiteCheck(
        website_id=1,
        requested_url="https://example.ca/",
        redirect_count=-1,
    )

    with pytest.raises(
        WebsiteCheckError,
        match="redirect_count",
    ):
        check.validate()
