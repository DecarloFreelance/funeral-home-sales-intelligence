from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .scalars import normalize_text

_STREET_TYPE_RULES = {
    "avenue": "avenue",
    "ave": "avenue",
    "av": "avenue",
    "boulevard": "boulevard",
    "blvd": "boulevard",
    "circle": "circle",
    "cir": "circle",
    "court": "court",
    "ct": "court",
    "crescent": "crescent",
    "cres": "crescent",
    "cr": "crescent",
    "drive": "drive",
    "dr": "drive",
    "highway": "highway",
    "hwy": "highway",
    "lane": "lane",
    "ln": "lane",
    "parkway": "parkway",
    "pkwy": "parkway",
    "place": "place",
    "pl": "place",
    "road": "road",
    "rd": "road",
    "route": "route",
    "rte": "route",
    "street": "street",
    "st": "street",
    "terrace": "terrace",
    "terr": "terrace",
    "trail": "trail",
    "trl": "trail",
    "way": "way",
    "rue": "rue",
    "chemin": "chemin",
    "ch": "chemin",
    "rang": "rang",
    "montée": "montee",
    "montee": "montee",
}

_DIRECTION_RULES = {
    "n": "north",
    "north": "north",
    "s": "south",
    "south": "south",
    "e": "east",
    "east": "east",
    "w": "west",
    "west": "west",
    "ne": "northeast",
    "northeast": "northeast",
    "nw": "northwest",
    "northwest": "northwest",
    "se": "southeast",
    "southeast": "southeast",
    "sw": "southwest",
    "southwest": "southwest",
    "nord": "north",
    "sud": "south",
    "est": "east",
    "ouest": "west",
}

_UNIT_PREFIX = re.compile(
    r"^(?P<prefix>unit|suite|ste|appartement|appt|bureau)\s*#?\s*(?P<unit>[A-Za-z0-9-]+)\s*[,;-]?\s*(?P<rest>.+)$",
    re.IGNORECASE,
)

_HASH_UNIT_PREFIX = re.compile(
    r"^#\s*(?P<unit>[A-Za-z0-9-]+)\s*[,;-]?\s*(?P<rest>.+)$",
)

_TRAILING_UNIT = re.compile(
    r"^(?P<rest>.+?)\s*[,;-]\s*(?:unit|suite|ste|appartement|appt|bureau)\s*#?\s*(?P<unit>[A-Za-z0-9-]+)$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class AddressNormalization:
    display_address: str | None
    comparison_key: str | None
    unit: str | None = None
    warnings: tuple[str, ...] = ()


def normalize_address(value: str | None) -> AddressNormalization:
    text = normalize_text(value)
    if text.value is None:
        return AddressNormalization(
            display_address=None,
            comparison_key=None,
            warnings=text.warnings,
        )

    display = text.value
    warnings = list(text.warnings)

    unit, street = _extract_unit(display)
    comparison = _comparison_text(street)
    comparison = _canonicalize_tokens(comparison)

    if unit is not None:
        comparison = f"{comparison} unit {unit.casefold()}"
        warnings.append("address unit normalized")

    if comparison != _comparison_text(display):
        warnings.append("address comparison key canonicalized")

    return AddressNormalization(
        display_address=display,
        comparison_key=comparison or None,
        unit=unit,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _extract_unit(value: str) -> tuple[str | None, str]:
    for pattern in (_UNIT_PREFIX, _HASH_UNIT_PREFIX):
        match = pattern.fullmatch(value)
        if match is not None:
            return match.group("unit"), match.group("rest").strip()

    trailing = _TRAILING_UNIT.fullmatch(value)
    if trailing is not None:
        return trailing.group("unit"), trailing.group("rest").strip()

    return None, value


def _comparison_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    cleaned = re.sub(r"[^a-z0-9]+", " ", without_marks)
    return " ".join(cleaned.split())


def _canonicalize_tokens(value: str) -> str:
    tokens = value.split()
    canonical: list[str] = []

    for index, token in enumerate(tokens):
        if token == "st" and index > 0 and tokens[index - 1].isdigit():
            canonical.append(token)
            continue
        if token in _STREET_TYPE_RULES:
            canonical.append(_STREET_TYPE_RULES[token])
            continue
        if token in _DIRECTION_RULES:
            canonical.append(_DIRECTION_RULES[token])
            continue
        canonical.append(token)

    return " ".join(canonical)
