from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser

from canada_funeral_intel.normalization.business_names import (
    normalize_business_name,
)

_SOFT_404_PHRASES = (
    "404 not found",
    "page not found",
    "page cannot be found",
    "page could not be found",
    "page does not exist",
    "page doesn't exist",
    "the page you are looking for",
    "the page you're looking for",
)

_PARKED_PHRASES = (
    "this domain is for sale",
    "domain is for sale",
    "buy this domain",
    "this domain is parked",
    "domain parking",
    "afternic",
    "sedo domain parking",
    "hugedomains",
)

_GENERIC_IDENTITY_TOKENS = frozenset(
    {
        "and",
        "centre",
        "chapel",
        "cremation",
        "crematorium",
        "funeral",
        "home",
        "memorial",
        "mortuary",
        "of",
        "services",
        "the",
    }
)


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self.parts: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del attrs
        if tag.casefold() in {"script", "style", "noscript"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "noscript"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0 and data.strip():
            self.parts.append(data)


@dataclass(frozen=True, slots=True)
class WebsiteContentAnalysis:
    soft_404: bool
    parked_or_for_sale: bool
    identity_score: float | None


def _visible_text(body: bytes, content_type: str | None) -> str:
    if content_type is None or "html" not in content_type.casefold():
        return ""

    parser = _VisibleTextParser()
    parser.feed(body.decode("utf-8", errors="replace"))
    return " ".join(" ".join(parser.parts).split()).casefold()


def _identity_score(
    visible_text: str,
    expected_business_name: str | None,
) -> float | None:
    if expected_business_name is None or not expected_business_name.strip():
        return None

    normalized = normalize_business_name(expected_business_name)
    key = normalized.comparison_key
    if key is None:
        return None

    tokens = [
        token
        for token in key.split()
        if token not in _GENERIC_IDENTITY_TOKENS and len(token) >= 3
    ]
    if not tokens:
        tokens = [token for token in key.split() if len(token) >= 3]
    if not tokens:
        return None

    observed_tokens = set(re.findall(r"[a-z0-9]+", visible_text))
    matched = sum(token in observed_tokens for token in tokens)
    return round(matched / len(tokens), 4)


def analyze_website_content(
    body: bytes,
    *,
    content_type: str | None,
    status_code: int | None,
    expected_business_name: str | None,
) -> WebsiteContentAnalysis:
    visible_text = _visible_text(body, content_type)

    soft_404 = (
        status_code is not None
        and 200 <= status_code < 300
        and any(phrase in visible_text for phrase in _SOFT_404_PHRASES)
    )
    parked = any(phrase in visible_text for phrase in _PARKED_PHRASES)

    return WebsiteContentAnalysis(
        soft_404=soft_404,
        parked_or_for_sale=parked,
        identity_score=_identity_score(
            visible_text,
            expected_business_name,
        ),
    )
