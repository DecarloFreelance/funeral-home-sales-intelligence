from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum
from html.parser import HTMLParser

from canada_funeral_intel.extraction.contact_analysis import extract_contact_values
from canada_funeral_intel.normalization.people import (
    normalize_person_name,
    normalize_role_title,
)

EXTRACTOR_VERSION = "phase8-v1"


class ExtractionMethod(StrEnum):
    STRUCTURED_ROLE_BLOCK = "structured_role_block"
    ROLE_ADJACENT_NAME = "role_adjacent_name"


class ExtractionSkipReason(StrEnum):
    NON_HTML = "non_html"
    NON_SUCCESS = "non_success"
    IDENTITY_NOT_OBSERVABLE = "identity_not_observable"
    EXCLUDED_CONTENT = "excluded_content"
    NO_ROLE_CONTEXT = "no_role_context"


@dataclass(frozen=True, slots=True)
class PersonObservationCandidate:
    observed_name: str
    normalized_name: str
    role_title: str
    normalized_role: str
    email: str | None
    normalized_email: str | None
    phone: str | None
    normalized_phone: str | None
    branch_context: str | None
    confidence: float
    extraction_method: ExtractionMethod
    evidence_snippet: str


@dataclass(frozen=True, slots=True)
class PersonAnalysisResult:
    candidates: tuple[PersonObservationCandidate, ...]
    rejected_candidates: int
    ambiguous_observations: int


@dataclass(slots=True)
class _Element:
    tag: str
    classes: str
    text: list[str]
    depth: int


_BLOCK_TAGS = frozenset({"article", "div", "li", "section", "tr", "address"})
_SKIP_TAGS = frozenset({"script", "style", "noscript", "nav", "footer"})
_ROLE_PATTERN = re.compile(
    r"\b((?:(?:licensed|managing|general|location|pre[- ]planning|family service|"
    r"vice|past)\s+)?"
    r"(?:funeral directors?|funeral home managers?|managers?|owners?|co-owners?|president|"
    r"managing partner|embalmer|director|counsell?or|counselor|professional))\b",
    re.IGNORECASE,
)
_NAME_PATTERN = re.compile(r"\b([A-Z][A-Za-z'’.-]+(?:\s+[A-Z][A-Za-z'’.-]+){1,3})\b")
_SEPARATOR_PATTERN = re.compile(r"\s*(?:[|–—:-]|\bat\b)\s*", re.IGNORECASE)
_NEGATIVE_PATTERN = re.compile(
    r"\b(?:obituar(?:y|ies)|death notice|tribute|memorial|guest book|"
    r"condolence|testimonial|customer review|web design|website design|"
    r"hosting|powered by|privacy policy|cookie policy|terms of service|"
    r"supplier|vendor|seo|marketing agency)\b",
    re.IGNORECASE,
)
_BRANCH_PATTERN = re.compile(
    r"\b(?:location|branch|serving|office)\s*[:\-]\s*([^|\n]+)",
    re.IGNORECASE,
)


class _BlockParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[_Element] = []
        self._stack: list[_Element] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        values = {name.casefold(): value or "" for name, value in attrs}
        classes = f"{values.get('class', '')} {values.get('id', '')}".casefold()
        if tag in _SKIP_TAGS or any(
            token in classes
            for token in (
                "footer",
                "navigation",
                "social",
                "testimonial",
                "review",
                "vendor",
                "credit",
                "obituary",
                "tribute",
                "memorial",
            )
        ):
            self._skip_depth += 1
            return
        if self._skip_depth:
            self._skip_depth += 1
            return
        if tag in _BLOCK_TAGS:
            self._stack.append(_Element(tag, classes, [], len(self._stack)))

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if self._skip_depth:
            self._skip_depth -= 1
            return
        if tag in _BLOCK_TAGS and self._stack:
            element = self._stack.pop()
            text = " ".join(" ".join(element.text).split())
            if text:
                self.blocks.append(
                    _Element(element.tag, element.classes, [text], element.depth)
                )

    def handle_data(self, data: str) -> None:
        if self._skip_depth or not data.strip():
            return
        for element in self._stack:
            element.text.append(data)


def _text_without_contacts(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z'’.-]+", " ", text)).strip()


_PAIRED_NAME_PATTERN = re.compile(
    r"\b([A-Z][A-Za-z'’.-]+)\s*&\s*([A-Z][A-Za-z'’.-]+)\s+"
    r"([A-Z][A-Za-z'’.-]+)\b"
)


def _name_fragments(fragment: str) -> tuple[str, ...]:
    paired = _PAIRED_NAME_PATTERN.search(fragment)
    if paired:
        first, second, surname = paired.groups()
        return (f"{first} {surname}", f"{second} {surname}")
    cleaned = _text_without_contacts(fragment)
    match = _NAME_PATTERN.search(cleaned)
    return (match.group(1),) if match else ()


def _names_and_role(text: str) -> tuple[tuple[str, ...], str, ExtractionMethod] | None:
    role_match = _ROLE_PATTERN.search(text)
    if role_match is None:
        return None
    role = " ".join(role_match.group(1).split())
    before = text[: role_match.start()]
    after = text[role_match.end() :]
    for fragment, method in (
        (before, ExtractionMethod.ROLE_ADJACENT_NAME),
        (after, ExtractionMethod.ROLE_ADJACENT_NAME),
    ):
        names = _name_fragments(fragment)
        if names:
            return names, role, method
    separator_parts = _SEPARATOR_PATTERN.split(text)
    for part in separator_parts:
        names = _name_fragments(part)
        if names:
            return names, role, ExtractionMethod.STRUCTURED_ROLE_BLOCK
    return None


def analyze_person_page(
    body: bytes, *, content_type: str | None
) -> PersonAnalysisResult:
    if content_type is None or "html" not in content_type.casefold():
        return PersonAnalysisResult((), 0, 0)

    parser = _BlockParser()
    parser.feed(body.decode("utf-8", errors="replace"))
    candidates: list[PersonObservationCandidate] = []
    rejected = 0
    ambiguous = 0
    seen: set[tuple[str, str, str, str]] = set()

    for block in parser.blocks:
        text = block.text[0]
        if _NEGATIVE_PATTERN.search(text):
            rejected += 1
            continue
        parsed = _names_and_role(text)
        if parsed is None:
            continue
        observed_names, role_title, method = parsed
        normalized_role = normalize_role_title(role_title).value
        if normalized_role is None:
            rejected += len(observed_names)
            continue
        email, normalized_email, phone, normalized_phone = extract_contact_values(text)
        branch_match = _BRANCH_PATTERN.search(text)
        branch_context = branch_match.group(1).strip() if branch_match else None
        for observed_name in observed_names:
            normalized_name = normalize_person_name(observed_name).value
            if normalized_name is None:
                rejected += 1
                continue
            key = (
                normalized_name,
                normalized_role,
                normalized_email or "",
                normalized_phone or "",
            )
            if key in seen:
                continue
            seen.add(key)
            confidence = 0.92 if method is ExtractionMethod.STRUCTURED_ROLE_BLOCK else 0.84
            if email or phone:
                confidence = min(0.98, confidence + 0.03)
            if branch_context:
                confidence = min(0.99, confidence + 0.02)
            candidates.append(
                PersonObservationCandidate(
                    observed_name=observed_name,
                    normalized_name=normalized_name,
                    role_title=role_title,
                    normalized_role=normalized_role,
                    email=email,
                    normalized_email=normalized_email,
                    phone=phone,
                    normalized_phone=normalized_phone,
                    branch_context=branch_context,
                    confidence=confidence,
                    extraction_method=method,
                    evidence_snippet=text[:500],
                )
            )

    return PersonAnalysisResult(tuple(candidates), rejected, ambiguous)


def content_hash(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()
