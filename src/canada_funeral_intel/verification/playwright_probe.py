from __future__ import annotations

from typing import Any, Self
from urllib.parse import urljoin, urlsplit

from canada_funeral_intel.normalization.scalars import normalize_domain
from canada_funeral_intel.verification.probe import (
    HTTPProbeResult,
    probe_http,
    resolve_public_addresses,
)


class PlaywrightProbeError(RuntimeError):
    """Raised when the optional Playwright browser cannot be started."""


class PlaywrightHTTPProbe:
    """Render one page at a time while preserving the HTTP probe result shape."""

    def __init__(self, *, user_agent: str, timeout_seconds: int, max_redirects: int):
        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds
        self.max_redirects = max_redirects
        self._playwright = None
        self._browser = None
        self._context = None

    def __enter__(self) -> Self:
        try:
            from playwright.sync_api import sync_playwright

            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=True)
            self._context = self._browser.new_context(user_agent=self.user_agent)
        except Exception as exc:
            self.close()
            raise PlaywrightProbeError(
                "Playwright is required for --engine playwright; "
                "install the browser extra and Chromium"
            ) from exc
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def close(self) -> None:
        if self._context is not None:
            self._context.close()
            self._context = None
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None

    def __call__(self, url: str) -> HTTPProbeResult:
        if self._context is None:
            raise PlaywrightProbeError("Playwright browser context is not active")
        preflight = probe_http(
            url,
            user_agent=self.user_agent,
            timeout_seconds=self.timeout_seconds,
            max_redirects=self.max_redirects,
        )
        if preflight.status_code is None or not 200 <= preflight.status_code < 400:
            return preflight

        browser_url = preflight.final_url or url
        hostname = urlsplit(browser_url).hostname
        if hostname is None:
            return preflight
        try:
            resolve_public_addresses(hostname)
        except Exception as exc:  # noqa: BLE001 - page-local network failure
            return HTTPProbeResult(
                requested_url=url,
                final_url=browser_url,
                status_code=None,
                redirect_count=preflight.redirect_count,
                response_time_ms=None,
                content_type=None,
                canonical_url=None,
                error_message=str(exc),
            )
        normalized_host = normalize_domain(hostname).value
        page = self._context.new_page()

        def route_request(route: Any, request: Any) -> None:
            request_url = urlsplit(str(request.url))
            request_host = (
                None
                if request_url.hostname is None
                else normalize_domain(request_url.hostname).value
            )
            if (
                request.resource_type in {"document", "xhr", "fetch"}
                and request_host != normalized_host
            ):
                route.abort()
            else:
                route.continue_()

        page.route("**/*", route_request)
        try:
            response = page.goto(
                browser_url,
                wait_until="domcontentloaded",
                timeout=self.timeout_seconds * 1000,
            )
            redirect_count = 0
            request = None if response is None else response.request
            while request is not None and request.redirected_from is not None:
                redirect_count += 1
                request = request.redirected_from
            if redirect_count > self.max_redirects:
                return HTTPProbeResult(
                    requested_url=url,
                    final_url=page.url,
                    status_code=None,
                    redirect_count=redirect_count,
                    response_time_ms=None,
                    content_type=None,
                    canonical_url=None,
                    error_message="maximum redirects exceeded",
                )

            headers = {} if response is None else response.headers
            content_type = headers.get("content-type")
            canonical_href = page.locator("link[rel~='canonical']").first.get_attribute(
                "href"
            )
            canonical_url = (
                None
                if not canonical_href
                else urljoin(page.url, canonical_href.strip())
            )
            return HTTPProbeResult(
                requested_url=url,
                final_url=page.url,
                status_code=None if response is None else response.status,
                redirect_count=redirect_count,
                response_time_ms=None,
                content_type=content_type,
                canonical_url=canonical_url,
                error_message=None,
                body=page.content().encode("utf-8"),
            )
        except Exception as exc:  # noqa: BLE001 - browser failures are page-local
            return HTTPProbeResult(
                requested_url=url,
                final_url=page.url,
                status_code=None,
                redirect_count=0,
                response_time_ms=None,
                content_type=None,
                canonical_url=None,
                error_message=str(exc),
            )
        finally:
            page.close()
