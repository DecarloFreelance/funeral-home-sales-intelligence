from __future__ import annotations

import socket

from canada_funeral_intel.verification.checks import (
    DNSStatus,
    TLSStatus,
    WebsiteCheckOutcome,
)
from canada_funeral_intel.verification.probe import (
    HTTPProbeResult,
    WebsiteProbeError,
    probe_http,
    probe_website,
    resolve_public_addresses,
)


def test_resolver_rejects_non_public_addresses(monkeypatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))
        ],
    )

    try:
        resolve_public_addresses("example.test")
    except WebsiteProbeError as exc:
        assert "non-public" in str(exc)
    else:
        raise AssertionError("non-public address should be rejected")


def test_probe_http_follows_bounded_redirect_and_extracts_canonical(
    monkeypatch,
) -> None:
    responses = iter(
        [
            (301, {"location": "/home"}, b""),
            (
                200,
                {"content-type": "text/html; charset=utf-8"},
                b'<html><head><link rel="canonical" href="/canonical"></head></html>',
            ),
        ]
    )

    monkeypatch.setattr(
        "canada_funeral_intel.verification.probe._single_http_request",
        lambda *args, **kwargs: next(responses),
    )

    result = probe_http(
        "https://example.ca/",
        user_agent="Test/1.0",
        timeout_seconds=5,
        max_redirects=2,
    )

    assert result.status_code == 200
    assert result.final_url == "https://example.ca/home"
    assert result.redirect_count == 1
    assert result.canonical_url == "https://example.ca/canonical"


def test_probe_http_stops_at_redirect_limit(monkeypatch) -> None:
    monkeypatch.setattr(
        "canada_funeral_intel.verification.probe._single_http_request",
        lambda *args, **kwargs: (302, {"location": "/again"}, b""),
    )

    result = probe_http(
        "https://example.ca/",
        user_agent="Test/1.0",
        timeout_seconds=5,
        max_redirects=1,
    )

    assert result.status_code is None
    assert result.redirect_count == 1
    assert result.error_message is not None
    assert "Redirect limit exceeded" in result.error_message


def test_probe_http_ignores_malformed_canonical_url(monkeypatch) -> None:
    monkeypatch.setattr(
        "canada_funeral_intel.verification.probe._single_http_request",
        lambda *args, **kwargs: (
            200,
            {"content-type": "text/html"},
            b'<link rel="canonical" href="javascript:void(0)">',
        ),
    )

    result = probe_http(
        "https://example.ca/",
        user_agent="Test/1.0",
        timeout_seconds=5,
    )

    assert result.canonical_url is None


def test_probe_website_dns_failure_returns_unreachable_check(monkeypatch) -> None:
    def fail_dns(hostname: str) -> tuple[str, ...]:
        raise WebsiteProbeError(f"DNS resolution failed for {hostname}")

    monkeypatch.setattr(
        "canada_funeral_intel.verification.probe.resolve_public_addresses",
        fail_dns,
    )

    check = probe_website(
        website_id=4,
        url="https://example.ca/",
        user_agent="Test/1.0",
        timeout_seconds=5,
    )

    assert check.dns_status is DNSStatus.FAILED
    assert check.tls_status is TLSStatus.NOT_CHECKED
    assert check.outcome is WebsiteCheckOutcome.UNREACHABLE


def test_probe_website_records_https_and_http_results(monkeypatch) -> None:
    monkeypatch.setattr(
        "canada_funeral_intel.verification.probe.resolve_public_addresses",
        lambda hostname: ("203.0.113.10",),
    )
    monkeypatch.setattr(
        "canada_funeral_intel.verification.probe.probe_tls",
        lambda hostname, address, **kwargs: (
            TLSStatus.OK,
            "2027-01-01T00:00:00Z",
        ),
    )

    def fake_http(url: str, **kwargs) -> HTTPProbeResult:
        if url.startswith("https://"):
            return HTTPProbeResult(
                requested_url=url,
                final_url="https://www.example.ca/",
                status_code=200,
                redirect_count=1,
                response_time_ms=125,
                content_type="text/html",
                canonical_url="https://www.example.ca/",
                error_message=None,
            )
        return HTTPProbeResult(
            requested_url=url,
            final_url="http://example.ca/",
            status_code=301,
            redirect_count=0,
            response_time_ms=40,
            content_type="text/html",
            canonical_url=None,
            error_message=None,
        )

    monkeypatch.setattr(
        "canada_funeral_intel.verification.probe.probe_http",
        fake_http,
    )

    check = probe_website(
        website_id=9,
        url="https://example.ca/",
        user_agent="Test/1.0",
        timeout_seconds=5,
    )

    assert check.dns_status is DNSStatus.OK
    assert check.tls_status is TLSStatus.OK
    assert check.https_status_code == 200
    assert check.http_status_code == 301
    assert check.redirect_count == 1
    assert check.final_url == "https://www.example.ca/"
    assert check.outcome is WebsiteCheckOutcome.REACHABLE
