from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

from canada_funeral_intel.normalization.scalars import normalize_url
from canada_funeral_intel.verification.checks import (
    DNSStatus,
    TLSStatus,
    WebsiteCheck,
    WebsiteCheckOutcome,
)
from canada_funeral_intel.verification.content_analysis import analyze_website_content

_MAX_BODY_BYTES = 131_072
_DEFAULT_MAX_REDIRECTS = 5
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class WebsiteProbeError(RuntimeError):
    """Raised when a website network probe cannot complete safely."""


@dataclass(frozen=True, slots=True)
class HTTPProbeResult:
    requested_url: str
    final_url: str | None
    status_code: int | None
    redirect_count: int
    response_time_ms: int | None
    content_type: str | None
    canonical_url: str | None
    error_message: str | None
    body: bytes = b""


class _CanonicalParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.canonical_href: str | None = None

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if self.canonical_href is not None or tag.casefold() != "link":
            return
        values = {name.casefold(): value for name, value in attrs}
        rel = (values.get("rel") or "").casefold().split()
        href = values.get("href")
        if "canonical" in rel and href:
            self.canonical_href = href.strip() or None


def _normalized_url(url: str) -> str:
    result = normalize_url(url)
    if result.value is None:
        raise WebsiteProbeError(f"Invalid HTTP(S) URL: {url!r}")
    return result.value


def _host_port(url: str) -> tuple[str, int, str]:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        raise WebsiteProbeError(f"Invalid HTTP(S) URL: {url!r}")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return parsed.hostname, port, parsed.scheme


def resolve_public_addresses(hostname: str) -> tuple[str, ...]:
    try:
        rows = socket.getaddrinfo(
            hostname,
            None,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise WebsiteProbeError(f"DNS resolution failed for {hostname}: {exc}") from exc

    addresses = sorted({str(row[4][0]) for row in rows})
    if not addresses:
        raise WebsiteProbeError(f"DNS resolution returned no addresses for {hostname}")

    blocked: list[str] = []
    for address in addresses:
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError as exc:
            raise WebsiteProbeError(
                f"DNS returned an invalid IP address for {hostname}: {address}"
            ) from exc
        if not parsed.is_global:
            blocked.append(address)

    if blocked:
        raise WebsiteProbeError(
            f"DNS for {hostname} resolved to non-public address(es): "
            + ", ".join(blocked)
        )

    return tuple(addresses)


def probe_tls(
    hostname: str,
    address: str,
    *,
    port: int = 443,
    timeout_seconds: int,
) -> tuple[TLSStatus, str | None]:
    context = ssl.create_default_context()
    try:
        with (
            socket.create_connection(
                (address, port),
                timeout=timeout_seconds,
            ) as raw_socket,
            context.wrap_socket(
                raw_socket,
                server_hostname=hostname,
            ) as tls_socket,
        ):
            certificate = tls_socket.getpeercert()
    except (OSError, ssl.SSLError) as exc:
        raise WebsiteProbeError(f"TLS handshake failed for {hostname}: {exc}") from exc

    not_after = certificate.get("notAfter")
    expires_at: str | None = None
    if isinstance(not_after, str) and not_after:
        try:
            expires_at = (
                datetime.fromtimestamp(
                    ssl.cert_time_to_seconds(not_after),
                    tz=UTC,
                )
                .isoformat()
                .replace("+00:00", "Z")
            )
        except (OverflowError, ValueError):
            expires_at = None

    return TLSStatus.OK, expires_at


def _canonical_from_body(
    body: bytes,
    *,
    base_url: str,
    content_type: str | None,
) -> str | None:
    if content_type is None or "html" not in content_type.casefold():
        return None

    parser = _CanonicalParser()
    parser.feed(body.decode("utf-8", errors="replace"))

    if parser.canonical_href is None:
        return None

    joined = urljoin(base_url, parser.canonical_href)
    normalized = normalize_url(joined)
    return normalized.value


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(
        self,
        hostname: str,
        address: str,
        *,
        port: int,
        timeout: int,
    ) -> None:
        super().__init__(hostname, port=port, timeout=timeout)
        self._address = address

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self._address, self.port),
            self.timeout,
            self.source_address,
        )


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        hostname: str,
        address: str,
        *,
        port: int,
        timeout: int,
    ) -> None:
        super().__init__(
            hostname,
            port=port,
            timeout=timeout,
            context=ssl.create_default_context(),
        )
        self._address = address

    def connect(self) -> None:
        raw_socket = socket.create_connection(
            (self._address, self.port),
            self.timeout,
            self.source_address,
        )
        try:
            self.sock = self._context.wrap_socket(
                raw_socket,
                server_hostname=self.host,
            )
        except (OSError, ValueError, ssl.SSLError):
            raw_socket.close()
            raise


def _single_http_request(
    url: str,
    *,
    user_agent: str,
    timeout_seconds: int,
) -> tuple[int, dict[str, str], bytes]:
    parsed = urlsplit(url)
    hostname = parsed.hostname
    if hostname is None:
        raise WebsiteProbeError(f"URL has no hostname: {url!r}")

    addresses = resolve_public_addresses(hostname)
    address = addresses[0]

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    target = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))

    connection_cls = (
        _PinnedHTTPSConnection if parsed.scheme == "https" else _PinnedHTTPConnection
    )
    connection = connection_cls(
        hostname,
        address,
        port=port,
        timeout=timeout_seconds,
    )
    try:
        connection.request(
            "GET",
            target,
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.1",
                "Connection": "close",
            },
        )
        response = connection.getresponse()
        headers = {key.casefold(): value for key, value in response.getheaders()}
        body = response.read(_MAX_BODY_BYTES)
        return int(response.status), headers, body
    except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
        raise WebsiteProbeError(f"HTTP request failed for {url}: {exc}") from exc
    finally:
        connection.close()


def probe_http(
    url: str,
    *,
    user_agent: str,
    timeout_seconds: int,
    max_redirects: int = _DEFAULT_MAX_REDIRECTS,
) -> HTTPProbeResult:
    if max_redirects < 0:
        raise WebsiteProbeError("max_redirects must not be negative")

    requested_url = _normalized_url(url)
    current_url = requested_url
    started = time.monotonic()
    redirects = 0

    try:
        while True:
            status, headers, body = _single_http_request(
                current_url,
                user_agent=user_agent,
                timeout_seconds=timeout_seconds,
            )

            if status in _REDIRECT_STATUSES:
                location = headers.get("location")
                if location:
                    if redirects >= max_redirects:
                        raise WebsiteProbeError(
                            f"Redirect limit exceeded ({max_redirects})"
                        )
                    redirects += 1
                    current_url = _normalized_url(urljoin(current_url, location))
                    continue

            elapsed_ms = max(0, round((time.monotonic() - started) * 1000))
            content_type = headers.get("content-type")
            canonical_url = _canonical_from_body(
                body,
                base_url=current_url,
                content_type=content_type,
            )
            return HTTPProbeResult(
                requested_url=requested_url,
                final_url=current_url,
                status_code=status,
                redirect_count=redirects,
                response_time_ms=elapsed_ms,
                content_type=content_type,
                canonical_url=canonical_url,
                error_message=None,
                body=body,
            )
    except WebsiteProbeError as exc:
        elapsed_ms = max(0, round((time.monotonic() - started) * 1000))
        return HTTPProbeResult(
            requested_url=requested_url,
            final_url=None,
            status_code=None,
            redirect_count=redirects,
            response_time_ms=elapsed_ms,
            content_type=None,
            canonical_url=None,
            error_message=str(exc),
        )


def _scheme_url(url: str, scheme: str) -> str:
    parsed = urlsplit(_normalized_url(url))
    hostname = parsed.hostname
    if hostname is None:
        raise WebsiteProbeError(f"URL has no hostname: {url!r}")
    netloc = f"[{hostname}]" if ":" in hostname else hostname
    return urlunsplit(
        (
            scheme,
            netloc,
            parsed.path or "/",
            parsed.query,
            "",
        )
    )


def probe_website(
    *,
    website_id: int,
    url: str,
    user_agent: str,
    timeout_seconds: int,
    max_redirects: int = _DEFAULT_MAX_REDIRECTS,
    expected_business_name: str | None = None,
) -> WebsiteCheck:
    if website_id < 1:
        raise WebsiteProbeError("website_id must be a positive integer")
    if timeout_seconds < 1:
        raise WebsiteProbeError("timeout_seconds must be at least 1")
    if not user_agent.strip():
        raise WebsiteProbeError("user_agent must not be empty")

    requested_url = _normalized_url(url)
    hostname, https_port, _ = _host_port(_scheme_url(requested_url, "https"))

    try:
        addresses = resolve_public_addresses(hostname)
        dns_status = DNSStatus.OK
        dns_error = None
    except WebsiteProbeError as exc:
        return WebsiteCheck(
            website_id=website_id,
            requested_url=requested_url,
            dns_status=DNSStatus.FAILED,
            tls_status=TLSStatus.NOT_CHECKED,
            outcome=WebsiteCheckOutcome.UNREACHABLE,
            error_message=str(exc),
        )

    tls_status = TLSStatus.FAILED
    tls_expires_at: str | None = None
    tls_error: str | None = None
    try:
        tls_status, tls_expires_at = probe_tls(
            hostname,
            addresses[0],
            port=https_port,
            timeout_seconds=timeout_seconds,
        )
    except WebsiteProbeError as exc:
        tls_error = str(exc)

    https_result = probe_http(
        _scheme_url(requested_url, "https"),
        user_agent=user_agent,
        timeout_seconds=timeout_seconds,
        max_redirects=max_redirects,
    )
    http_result = probe_http(
        _scheme_url(requested_url, "http"),
        user_agent=user_agent,
        timeout_seconds=timeout_seconds,
        max_redirects=max_redirects,
    )

    preferred = (
        https_result
        if https_result.status_code is not None
        else http_result
        if http_result.status_code is not None
        else https_result
    )

    reachable = (
        https_result.status_code is not None or http_result.status_code is not None
    )

    errors = [
        value
        for value in (
            dns_error,
            tls_error,
            https_result.error_message,
            http_result.error_message,
        )
        if value
    ]

    analysis = analyze_website_content(
        preferred.body,
        content_type=preferred.content_type,
        status_code=preferred.status_code,
        expected_business_name=expected_business_name,
    )

    if not reachable:
        outcome = WebsiteCheckOutcome.UNREACHABLE
    elif analysis.parked_or_for_sale:
        outcome = WebsiteCheckOutcome.PARKED
    elif analysis.identity_score is not None and analysis.identity_score < 0.25:
        outcome = WebsiteCheckOutcome.MISMATCH
    else:
        outcome = WebsiteCheckOutcome.REACHABLE

    check = WebsiteCheck(
        website_id=website_id,
        requested_url=requested_url,
        final_url=preferred.final_url,
        dns_status=dns_status,
        dns_addresses=addresses,
        tls_status=tls_status,
        tls_expires_at=tls_expires_at,
        https_status_code=https_result.status_code,
        http_status_code=http_result.status_code,
        redirect_count=preferred.redirect_count,
        response_time_ms=preferred.response_time_ms,
        content_type=preferred.content_type,
        canonical_url=preferred.canonical_url,
        soft_404=analysis.soft_404,
        parked_or_for_sale=analysis.parked_or_for_sale,
        identity_score=analysis.identity_score,
        outcome=outcome,
        error_message="; ".join(errors) if errors and not reachable else None,
    )
    check.validate()
    return check
