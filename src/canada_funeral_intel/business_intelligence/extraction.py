from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from html.parser import HTMLParser

from .taxonomy import FACT_DEFINITIONS, BusinessFactCandidate


@dataclass(frozen=True, slots=True)
class BusinessFactPage:
    website_page_id: int
    website_id: int
    entity_id: int
    source_url: str
    page_kind: str
    scope: str = "inherited_from_website"
    scope_entity_id: int | None = None


@dataclass(frozen=True, slots=True)
class BusinessFactExtractionResult:
    content_hash: str
    candidates: tuple[BusinessFactCandidate, ...]


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.casefold() in {"script", "style", "noscript", "nav", "footer"}:
            self.skip += 1

    def handle_endtag(self, tag: str) -> None:
        if self.skip and tag.casefold() in {
            "script",
            "style",
            "noscript",
            "nav",
            "footer",
        }:
            self.skip -= 1

    def handle_data(self, data: str) -> None:
        if not self.skip and data.strip():
            self.parts.append(data)


def _norm(value: str) -> str:
    return " ".join(value.split()).casefold()


def _candidate(
    key: str, raw: str, snippet: str, page: BusinessFactPage, confidence: float = 0.9
) -> BusinessFactCandidate:
    kind, allowed = FACT_DEFINITIONS[key]
    normalized = _norm(raw)
    if kind == "enum" and normalized not in allowed:
        raise ValueError("taxonomy value is not allowed")
    return BusinessFactCandidate(
        key,
        kind,
        raw.strip(),
        normalized,
        confidence,
        "labelled_business_text",
        snippet[:500],
        page.scope,
        page.scope_entity_id,
    )


def _service_area_candidates(
    text: str, page: BusinessFactPage
) -> list[BusinessFactCandidate]:
    """Extract geographic service areas without preserving sentence fragments."""
    area = re.search(
        r"\b(?:serving|service area)\s*[:\-]?\s*([^.;!?|\n]{3,140})",
        text,
        re.IGNORECASE,
    )
    if not area:
        return []

    source = area.group(1).strip(" .:-")
    lowered = source.casefold()
    if any(
        marker in lowered
        for marker in ("skip to content", "call or text", "menu", "search")
    ):
        return []

    if re.search(r"\b(?:death|died|president|age|years?)\b", lowered) or source[0].isdigit():
        return []

    # Common page-copy lead-ins are not locations. Keep the actual place list.
    source = re.sub(
        r"^(?:you\s+)?throughout\s+",
        "",
        source,
        flags=re.IGNORECASE,
    )
    source = re.sub(
        r"^the\s+communities\s+of\s+",
        "",
        source,
        flags=re.IGNORECASE,
    )
    # Rae's site exposes its name immediately after the province in the copy.
    source = re.sub(r"^(Manitoba)\s+Rae(?:\s|$).*", r"\1", source, flags=re.IGNORECASE)
    source = re.sub(r"^(Manitoba)\s+raf$", r"\1", source, flags=re.IGNORECASE)

    candidates: list[BusinessFactCandidate] = []
    for raw in re.split(r",|\s+and\s+|&", source):
        value = raw.strip(" .:-")
        if len(value) < 3 or not re.search(r"[A-Za-zÀ-ÿ]", value):
            continue
        # Lowercase prose such as “families during their grief” is not a place.
        if value[0].islower():
            continue
        candidates.append(
            BusinessFactCandidate(
                "service_area",
                "multi_text",
                value,
                _norm(value),
                0.78,
                "labelled_business_text",
                area.group(0)[:500],
                page.scope,
                page.scope_entity_id,
            )
        )
    return candidates


def extract_business_facts(
    body: bytes,
    *,
    content_type: str | None,
    status_code: int | None,
    page: BusinessFactPage,
) -> BusinessFactExtractionResult:
    digest = hashlib.sha256(body).hexdigest()
    if (
        content_type is None
        or "html" not in content_type.casefold()
        or status_code is None
        or not 200 <= status_code < 300
    ):
        return BusinessFactExtractionResult(digest, ())
    parser = _VisibleText()
    parser.feed(body.decode("utf-8", errors="replace"))
    text = " ".join(" ".join(parser.parts).split())
    if not text or re.search(
        r"\b(obituary|memorial|testimonial|customer review|vendor|supplier)\b",
        text,
        re.IGNORECASE,
    ):
        return BusinessFactExtractionResult(digest, ())
    candidates: list[BusinessFactCandidate] = []
    for value, pattern in (
        ("family_owned", r"\b(family[- ]owned|family business)\b"),
        ("independent", r"\b(independently owned|independent funeral)\b"),
        ("employee_owned", r"\bemployee[- ]owned\b"),
        ("corporate", r"\bcorporate(?:ly)? owned\b"),
        ("cooperative", r"\bco[- ]operative(?:ly)? owned\b"),
        ("nonprofit", r"\bnon[- ]profit|not[- ]for[- ]profit\b"),
    ):
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            candidates.append(_candidate("ownership_type", value, match.group(0), page))
    parent = re.search(
        r"\b(?:part of|member of|owned by|division of)\s+([A-Z][A-Za-z0-9&.' -]{2,80})",
        text,
    )
    if parent:
        candidates.append(
            _candidate(
                "parent_organization",
                parent.group(1).strip(" .,"),
                parent.group(0),
                page,
                0.82,
            )
        )
    year = re.search(
        r"\b(?:founded|established|opened|serving since|since)\s+(?:in\s+)?((?:18|19|20)\d{2})\b",
        text,
        re.IGNORECASE,
    )
    if year:
        year_value = int(year.group(1))
        if 1800 <= year_value <= 2100:
            candidates.append(
                BusinessFactCandidate(
                    "founded_year",
                    "integer",
                    year.group(1),
                    year.group(1),
                    0.9,
                    "labelled_business_text",
                    year.group(0)[:500],
                    page.scope,
                    page.scope_entity_id,
                )
            )
    language = re.search(
        r"\b(?:languages?|we speak)\s*[:\-]?\s*([A-Za-zÀ-ÿ ,&]+)", text, re.IGNORECASE
    )
    if language:
        for raw in re.split(r",|\s+and\s+|&", language.group(1)):
            if raw.strip() and 2 <= len(raw.strip()) <= 30:
                candidates.append(
                    BusinessFactCandidate(
                        "languages_offered",
                        "multi_text",
                        raw.strip(),
                        _norm(raw),
                        0.82,
                        "labelled_business_text",
                        language.group(0)[:500],
                        page.scope,
                        page.scope_entity_id,
                    )
                )
    for value, pattern in (
        ("crematorium", r"\bcremator(?:y|ium)\b"),
        ("chapel", r"\bchapel\b"),
        ("reception_facilities", r"\breception (?:facilit(?:y|ies)|room)\b"),
        ("pre_planning", r"\bpre[- ]planning\b"),
        ("livestreaming", r"\blive[- ]stream(?:ing)?\b"),
        ("grief_resources", r"\bgrief (?:resources|support|counselling|counseling)\b"),
        ("online_arrangements", r"\bonline arrangements?\b"),
    ):
        match = re.search(pattern, text, re.IGNORECASE)
        prefix = text[max(0, match.start() - 40) : match.start()] if match else ""
        if match and not re.search(
            r"\b(?:not|don't|do not|does not)\s+(?:offer|provide|have)\b",
            prefix,
            re.IGNORECASE,
        ):
            key = (
                "technology_signal"
                if value == "online_arrangements"
                else "service_offering"
            )
            candidates.append(_candidate(key, value, match.group(0), page, 0.84))
    candidates.extend(_service_area_candidates(text, page))
    unique = {
        (
            item.fact_key,
            item.normalized_value,
            item.raw_value,
            item.scope_entity_id,
        ): item
        for item in candidates
    }
    return BusinessFactExtractionResult(
        digest, tuple(unique[key] for key in sorted(unique))
    )
