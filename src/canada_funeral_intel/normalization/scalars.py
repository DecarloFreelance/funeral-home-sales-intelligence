from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

_CANADIAN_POSTAL_CODE = re.compile(
    r"^[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z]\d[ABCEGHJ-NPRSTV-Z]\d$",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_PROVINCES = {
    "ab": "AB",
    "alberta": "AB",
    "bc": "BC",
    "british columbia": "BC",
    "colombie-britannique": "BC",
    "mb": "MB",
    "manitoba": "MB",
    "nb": "NB",
    "new brunswick": "NB",
    "nouveau-brunswick": "NB",
    "nl": "NL",
    "newfoundland and labrador": "NL",
    "terre-neuve-et-labrador": "NL",
    "ns": "NS",
    "nova scotia": "NS",
    "nouvelle-écosse": "NS",
    "nt": "NT",
    "northwest territories": "NT",
    "territoires du nord-ouest": "NT",
    "nu": "NU",
    "nunavut": "NU",
    "on": "ON",
    "ontario": "ON",
    "pe": "PE",
    "pei": "PE",
    "prince edward island": "PE",
    "île-du-prince-édouard": "PE",
    "qc": "QC",
    "pq": "QC",
    "quebec": "QC",
    "québec": "QC",
    "sk": "SK",
    "saskatchewan": "SK",
    "yt": "YT",
    "yukon": "YT",
}


@dataclass(frozen=True, slots=True)
class ScalarNormalization:
    value: str | None
    warnings: tuple[str, ...] = ()


def normalize_text(value: str | None) -> ScalarNormalization:
    if value is None:
        return ScalarNormalization(None)

    collapsed = " ".join(value.split())
    warnings: list[str] = []

    if collapsed != value:
        warnings.append("whitespace normalized")

    if not collapsed:
        return ScalarNormalization(None, (*warnings, "empty value"))

    return ScalarNormalization(collapsed, tuple(warnings))


def normalize_city(value: str | None) -> ScalarNormalization:
    return normalize_text(value)


def normalize_province(value: str | None) -> ScalarNormalization:
    text = normalize_text(value)
    if text.value is None:
        return text

    province = _PROVINCES.get(text.value.casefold())
    if province is None:
        return ScalarNormalization(
            None,
            (*text.warnings, "unrecognized Canadian province or territory"),
        )

    warnings = list(text.warnings)
    if province != text.value:
        warnings.append("province normalized to postal abbreviation")
    return ScalarNormalization(province, tuple(warnings))


def normalize_postal_code(value: str | None) -> ScalarNormalization:
    text = normalize_text(value)
    if text.value is None:
        return text

    compact = re.sub(r"[\s-]+", "", text.value).upper()
    if not _CANADIAN_POSTAL_CODE.fullmatch(compact):
        return ScalarNormalization(
            None,
            (*text.warnings, "invalid Canadian postal code"),
        )

    normalized = f"{compact[:3]} {compact[3:]}"
    warnings = list(text.warnings)
    if normalized != text.value:
        warnings.append("postal code normalized")
    return ScalarNormalization(normalized, tuple(warnings))


def normalize_email(value: str | None) -> ScalarNormalization:
    text = normalize_text(value)
    if text.value is None:
        return text

    candidate = text.value.casefold()
    if not _EMAIL.fullmatch(candidate):
        return ScalarNormalization(None, (*text.warnings, "invalid email address"))

    warnings = list(text.warnings)
    if candidate != text.value:
        warnings.append("email lowercased")
    return ScalarNormalization(candidate, tuple(warnings))


def normalize_phone(value: str | None) -> ScalarNormalization:
    text = normalize_text(value)
    if text.value is None:
        return text

    extension_match = re.search(
        r"(?:ext\.?|extension|x)\s*(\d+)\s*$",
        text.value,
        flags=re.IGNORECASE,
    )
    base = text.value
    extension: str | None = None
    if extension_match is not None:
        extension = extension_match.group(1)
        base = text.value[: extension_match.start()]

    digits = re.sub(r"\D", "", base)
    warnings = list(text.warnings)

    if len(digits) == 10:
        digits = "1" + digits
        warnings.append("Canadian country code inferred")
    elif len(digits) == 11 and digits.startswith("1"):
        pass
    else:
        return ScalarNormalization(
            None, (*warnings, "invalid North American phone number")
        )

    normalized = f"+{digits}"
    if extension is not None:
        normalized = f"{normalized} x{extension}"

    if normalized != text.value:
        warnings.append("phone normalized")
    return ScalarNormalization(normalized, tuple(warnings))


def normalize_url(value: str | None) -> ScalarNormalization:
    text = normalize_text(value)
    if text.value is None:
        return text

    candidate = text.value
    warnings = list(text.warnings)

    if "://" not in candidate:
        candidate = "https://" + candidate
        warnings.append("HTTPS scheme inferred")

    parsed = urlsplit(candidate)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        return ScalarNormalization(None, (*warnings, "invalid HTTP(S) URL"))

    try:
        port = parsed.port
    except ValueError:
        return ScalarNormalization(None, (*warnings, "invalid URL port"))

    host = parsed.hostname.casefold()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"

    netloc = host
    if port is not None:
        netloc = f"{netloc}:{port}"

    path = parsed.path or "/"
    normalized = urlunsplit((parsed.scheme.casefold(), netloc, path, parsed.query, ""))

    if normalized != text.value:
        warnings.append("URL normalized")
    return ScalarNormalization(normalized, tuple(warnings))


def normalize_domain(value: str | None) -> ScalarNormalization:
    text = normalize_text(value)
    if text.value is None:
        return text

    candidate = text.value
    if "://" not in candidate:
        candidate = "https://" + candidate

    parsed = urlsplit(candidate)
    if not parsed.hostname:
        return ScalarNormalization(None, (*text.warnings, "invalid domain"))

    domain = parsed.hostname.casefold().rstrip(".")
    domain = domain.removeprefix("www.")

    if "." not in domain or any(not label for label in domain.split(".")):
        return ScalarNormalization(None, (*text.warnings, "invalid domain"))

    warnings = list(text.warnings)
    if domain != text.value:
        warnings.append("domain normalized")
    return ScalarNormalization(domain, tuple(warnings))
