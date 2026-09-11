"""LangSearch web-search provider.

Thin, fail-closed HTTP client for the LangSearch web search API
(https://docs.langsearch.com/api/web-search-api), used by
resolve_955_websites.py to discover official-website *candidates* for
directory businesses. This module performs discovery only: it never claims
that a search result is an official site. Verification happens later, in
verify_955_websites.py / verify_langsearch_recovery_v2.py.

Requires a LANGSEARCH_API_KEY environment variable (free-tier key from
https://langsearch.com/dashboard). No key means no network call: callers get
a LangSearchError immediately rather than a silent skip or a fabricated
empty-but-successful result.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

import requests

API_URL = "https://api.langsearch.com/v1/web-search"
USER_AGENT = (
    "Mozilla/5.0 (compatible; FuneralHomeSalesIntelligence/1.0; "
    "LangSearchProvider; discovery-only)"
)


class LangSearchError(RuntimeError):
    """Missing credentials, transport failure, or a malformed LangSearch
    response. Callers treat this as a per-query failure, not a reason to
    fabricate a result."""


class LangSearchProvider:
    """Rate-limited client for the LangSearch web search API.

    One provider instance is meant to be reused across a whole run so that
    ``min_interval`` throttles consecutive calls regardless of which record
    they belong to.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: float = 20.0,
        min_interval: float = 1.05,
        session: Optional[requests.Session] = None,
    ):
        self.api_key = api_key or os.environ.get("LANGSEARCH_API_KEY", "")
        self.timeout = timeout
        self.min_interval = max(0.0, min_interval)
        self._session = session or requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT})
        self._last_request_at: Optional[float] = None

    def _throttle(self) -> None:
        if self._last_request_at is None or self.min_interval <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.min_interval - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def search(
        self,
        query: str,
        limit: int = 10,
        freshness: str = "noLimit",
        summary: bool = False,
    ) -> Dict[str, Any]:
        """Run one LangSearch web-search query.

        Returns ``{"results": [...], "log_id": ..., "query": ...,
        "total_estimated_matches": ...}``. Each result dict always has a
        non-empty ``url``; malformed candidate entries are dropped rather
        than raising, since one bad entry should not fail a whole query.
        """
        if not query or not query.strip():
            raise ValueError("query must be a non-empty string")
        if not self.api_key:
            raise LangSearchError(
                "LANGSEARCH_API_KEY is not set; refusing to call the "
                "LangSearch API without credentials."
            )

        count = max(1, min(10, int(limit)))
        self._throttle()

        try:
            response = self._session.post(
                API_URL,
                json={
                    "query": query,
                    "freshness": freshness,
                    "summary": summary,
                    "count": count,
                },
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=(5, self.timeout),
            )
        except requests.RequestException as exc:
            self._last_request_at = time.monotonic()
            raise LangSearchError(f"LangSearch request failed: {exc}") from exc

        self._last_request_at = time.monotonic()

        if response.status_code != 200:
            detail = (response.text or "")[:200]
            raise LangSearchError(
                f"LangSearch returned HTTP {response.status_code}: {detail}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise LangSearchError("LangSearch returned a non-JSON response") from exc

        if not isinstance(payload, dict):
            raise LangSearchError("LangSearch response body was not a JSON object")

        code = payload.get("code")
        if code not in (200, None):
            raise LangSearchError(
                f"LangSearch reported an error (code={code}): {payload.get('msg')}"
            )

        web_pages = (payload.get("data") or {}).get("webPages") or {}
        raw_results = web_pages.get("value") or []
        if not isinstance(raw_results, list):
            raise LangSearchError("LangSearch response 'webPages.value' was not a list")

        results: List[Dict[str, Any]] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            if not url:
                continue
            results.append(
                {
                    "url": url,
                    "title": item.get("name", ""),
                    "snippet": item.get("snippet", ""),
                    "summary": item.get("summary", ""),
                    "display_url": item.get("displayUrl", ""),
                }
            )

        return {
            "results": results,
            "log_id": payload.get("log_id"),
            "query": query,
            "total_estimated_matches": web_pages.get("totalEstimatedMatches"),
        }
