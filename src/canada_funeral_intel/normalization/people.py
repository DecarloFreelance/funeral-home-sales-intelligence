from __future__ import annotations

import re

from .scalars import ScalarNormalization, normalize_text

_PERSON_PUNCTUATION = re.compile(r"[^\w'’.-]+", re.UNICODE)
_ROLE_PUNCTUATION = re.compile(r"[^\w/ &-]+", re.UNICODE)


def normalize_person_name(value: str | None) -> ScalarNormalization:
    text = normalize_text(value)
    if text.value is None:
        return text

    cleaned = _PERSON_PUNCTUATION.sub(" ", text.value)
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        return ScalarNormalization(None, (*text.warnings, "empty person name"))

    normalized = cleaned.casefold()
    warnings = list(text.warnings)
    if normalized != text.value.casefold():
        warnings.append("person name normalized")
    return ScalarNormalization(normalized, tuple(warnings))


def normalize_role_title(value: str | None) -> ScalarNormalization:
    text = normalize_text(value)
    if text.value is None:
        return text

    cleaned = _ROLE_PUNCTUATION.sub(" ", text.value)
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        return ScalarNormalization(None, (*text.warnings, "empty role title"))

    normalized = cleaned.casefold()
    warnings = list(text.warnings)
    if normalized != text.value.casefold():
        warnings.append("role title normalized")
    return ScalarNormalization(normalized, tuple(warnings))
