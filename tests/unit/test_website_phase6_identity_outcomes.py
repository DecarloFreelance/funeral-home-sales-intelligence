from __future__ import annotations

from canada_funeral_intel.verification.checks import (
    TLSStatus,
    WebsiteCheckOutcome,
)
from canada_funeral_intel.verification.probe import (
    HTTPProbeResult,
    probe_website,
)


def _result(
    url: str,
    *,
    status: int,
    body: bytes,
    content_type: str = "text/html",
) -> HTTPProbeResult:
    return HTTPProbeResult(
        requested_url=url,
        final_url=url,
        status_code=status,
        redirect_count=0,
        response_time_ms=5,
        content_type=content_type,
        canonical_url=None,
        error_message=None,
        body=body,
    )


def _patch_network(
    monkeypatch,
    *,
    https_result: HTTPProbeResult,
    http_result: HTTPProbeResult,
) -> None:
    monkeypatch.setattr(
        "canada_funeral_intel.verification.probe.resolve_public_addresses",
        lambda hostname: ("203.0.113.10",),
    )

    monkeypatch.setattr(
        "canada_funeral_intel.verification.probe.probe_tls",
        lambda hostname, address, **kwargs: (
            TLSStatus.OK,
            "2030-01-01T00:00:00Z",
        ),
    )

    results = iter(
        (
            https_result,
            http_result,
        )
    )

    monkeypatch.setattr(
        "canada_funeral_intel.verification.probe.probe_http",
        lambda url, **kwargs: next(results),
    )


def test_403_low_identity_is_inconclusive_not_mismatch(
    monkeypatch,
) -> None:
    https = _result(
        "https://fixture.ca/",
        status=403,
        body=b"<html><body>Access denied</body></html>",
    )
    http = _result(
        "http://fixture.ca/",
        status=403,
        body=b"<html><body>Access denied</body></html>",
    )

    _patch_network(
        monkeypatch,
        https_result=https,
        http_result=http,
    )

    check = probe_website(
        website_id=1,
        url="https://fixture.ca/",
        user_agent="Test/1.0",
        timeout_seconds=5,
        expected_business_name="Prairie Funeral Home",
    )

    assert check.identity_score == 0.0
    assert check.outcome is WebsiteCheckOutcome.UNKNOWN


def test_successful_html_low_identity_can_be_verified_mismatch(
    monkeypatch,
) -> None:
    https = _result(
        "https://fixture.ca/",
        status=200,
        body=(b"<html><body>Completely Different Corporation</body></html>"),
    )
    http = _result(
        "http://fixture.ca/",
        status=200,
        body=(b"<html><body>Completely Different Corporation</body></html>"),
    )

    _patch_network(
        monkeypatch,
        https_result=https,
        http_result=http,
    )

    check = probe_website(
        website_id=1,
        url="https://fixture.ca/",
        user_agent="Test/1.0",
        timeout_seconds=5,
        expected_business_name="Prairie Funeral Home",
        allow_identity_mismatch=True,
    )

    assert check.identity_score == 0.0
    assert check.outcome is WebsiteCheckOutcome.MISMATCH


def test_shared_root_low_identity_is_inconclusive(
    monkeypatch,
) -> None:
    https = _result(
        "https://parent.example/",
        status=200,
        body=(b"<html><body>Parent Memorial Corporation</body></html>"),
    )
    http = _result(
        "http://parent.example/",
        status=200,
        body=(b"<html><body>Parent Memorial Corporation</body></html>"),
    )

    _patch_network(
        monkeypatch,
        https_result=https,
        http_result=http,
    )

    check = probe_website(
        website_id=1,
        url="https://parent.example/",
        user_agent="Test/1.0",
        timeout_seconds=5,
        expected_business_name="South Branch Funeral Home",
        allow_identity_mismatch=False,
    )

    assert check.identity_score == 0.0
    assert check.outcome is WebsiteCheckOutcome.UNKNOWN


def test_shared_root_strong_identity_remains_reachable(
    monkeypatch,
) -> None:
    https = _result(
        "https://shared.example/",
        status=200,
        body=(b"<html><body>Mackenzie Funeral Service</body></html>"),
    )
    http = _result(
        "http://shared.example/",
        status=200,
        body=(b"<html><body>Mackenzie Funeral Service</body></html>"),
    )

    _patch_network(
        monkeypatch,
        https_result=https,
        http_result=http,
    )

    check = probe_website(
        website_id=1,
        url="https://shared.example/",
        user_agent="Test/1.0",
        timeout_seconds=5,
        expected_business_name="Mackenzie Funeral Service",
        allow_identity_mismatch=False,
    )

    assert check.identity_score == 1.0
    assert check.outcome is WebsiteCheckOutcome.REACHABLE
