from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .scalars import normalize_text

_LEGAL_SUFFIXES = (
    "incorporated",
    "inc",
    "limited",
    "ltd",
    "corporation",
    "corp",
)

_TERMINOLOGY_RULES = (
    (re.compile(r"\bmaisons?\s+fun[eé]raires?\b", re.IGNORECASE), "funeral home"),
    (re.compile(r"\bsalons?\s+fun[eé]raires?\b", re.IGNORECASE), "funeral home"),
    (re.compile(r"\bfuneral\s+homes?\b", re.IGNORECASE), "funeral home"),
    (re.compile(r"\bfuneral\s+chapels?\b", re.IGNORECASE), "funeral chapel"),
    (re.compile(r"\bchapelles?\s+fun[eé]raires?\b", re.IGNORECASE), "funeral chapel"),
    (re.compile(r"\bcremation\s+cent(?:er|re)s?\b", re.IGNORECASE), "cremation centre"),
    (
        re.compile(r"\bcentres?\s+de\s+cr[eé]mation\b", re.IGNORECASE),
        "cremation centre",
    ),
    (re.compile(r"\bcr[eé]matoriums?\b", re.IGNORECASE), "crematorium"),
    (re.compile(r"\bcr[eé]matoires?\b", re.IGNORECASE), "crematorium"),
    (re.compile(r"\bmortuaries\b", re.IGNORECASE), "mortuary"),
)

_CANONICAL_TERMS = (
    "funeral home",
    "funeral chapel",
    "cremation centre",
    "crematorium",
    "mortuary",
    "memorial",
)


@dataclass(frozen=True, slots=True)
class BusinessNameNormalization:
    display_name: str | None
    comparison_key: str | None
    terminology: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def normalize_business_name(value: str | None) -> BusinessNameNormalization:
    text = normalize_text(value)
    if text.value is None:
        return BusinessNameNormalization(
            display_name=None,
            comparison_key=None,
            warnings=text.warnings,
        )

    display_name = text.value
    warnings = list(text.warnings)

    comparison = _comparison_text(display_name)
    canonicalized = comparison

    for pattern, replacement in _TERMINOLOGY_RULES:
        canonicalized = pattern.sub(replacement, canonicalized)

    canonicalized = _strip_legal_suffixes(canonicalized)
    canonicalized = _collapse_comparison_punctuation(canonicalized)

    terminology = tuple(
        term for term in _CANONICAL_TERMS if _contains_term(canonicalized, term)
    )

    if canonicalized != comparison:
        warnings.append("business name comparison key canonicalized")

    return BusinessNameNormalization(
        display_name=display_name,
        comparison_key=canonicalized or None,
        terminology=terminology,
        warnings=tuple(warnings),
    )


def _comparison_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return _collapse_comparison_punctuation(without_marks)


def _collapse_comparison_punctuation(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def _strip_legal_suffixes(value: str) -> str:
    tokens = value.split()
    while tokens and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def _contains_term(value: str, term: str) -> bool:
    pattern = rf"(?:^|\s){re.escape(term)}(?:\s|$)"
    return re.search(pattern, value) is not None
