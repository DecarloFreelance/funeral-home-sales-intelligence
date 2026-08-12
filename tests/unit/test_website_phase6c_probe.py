from __future__ import annotations

from canada_funeral_intel.verification.checks import TLSStatus, WebsiteCheckOutcome
from canada_funeral_intel.verification.probe import (
    HTTPProbeResult,
    probe_website,
)


def _install_network_fakes(monkeypatch, body: bytes) -> None:
    monkeypatch.setattr(
        "canada_funeral_intel.verification.probe.resolve_public_addresses",
        lambda hostname: ("203.0.113.50",),
    )
    monkeypatch.setattr(
        "canada_funeral_intel.verification.probe.probe_tls",
        lambda hostname, address, **kwargs: (TLSStatus.OK, None),
    )

    def fake_http(url: str, **kwargs) -> HTTPProbeResult:
        return HTTPProbeResult(
            requested_url=url,
            final_url=url,
            status_code=200,
            redirect_count=0,
            response_time_ms=20,
            content_type="text/html",
            canonical_url=None,
            error_message=None,
            body=body,
        )

    monkeypatch.setattr(
        "canada_funeral_intel.verification.probe.probe_http",
        fake_http,
    )


def test_probe_marks_parked_page_and_outcome(monkeypatch) -> None:
    _install_network_fakes(
        monkeypatch,
        b"<html><body>This domain is for sale</body></html>",
    )

    check = probe_website(
        website_id=1,
        url="https://example.ca/",
        user_agent="Test/1.0",
        timeout_seconds=5,
        expected_business_name="Prairie Rose Funeral Home",
    )

    assert check.parked_or_for_sale is True
    assert check.outcome is WebsiteCheckOutcome.PARKED


def test_probe_records_soft_404_and_identity_mismatch(monkeypatch) -> None:
    _install_network_fakes(
        monkeypatch,
        b"<html><body>Page not found. Mountain View Plumbing.</body></html>",
    )

    check = probe_website(
        website_id=2,
        url="https://example.ca/",
        user_agent="Test/1.0",
        timeout_seconds=5,
        expected_business_name="Prairie Rose Funeral Home",
    )

    assert check.soft_404 is True
    assert check.identity_score == 0.0
    assert check.outcome is WebsiteCheckOutcome.MISMATCH
