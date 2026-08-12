from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlparse


class SourceRegistryError(ValueError):
    """Raised when source registry metadata is invalid."""


class SourceType(StrEnum):
    GOVERNMENT = "government"
    REGULATOR = "regulator"
    ASSOCIATION = "association"
    OPEN_DATA = "open_data"
    COMMERCIAL = "commercial"
    MANUAL = "manual"


class SourceFormat(StrEnum):
    CSV = "csv"
    JSON = "json"
    HTML = "html"
    XML = "xml"
    XLSX = "xlsx"
    PDF = "pdf"
    MANUAL = "manual"


class TrustLevel(StrEnum):
    AUTHORITATIVE = "authoritative"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True, slots=True)
class SourceDefinition:
    name: str
    source_type: SourceType
    source_format: SourceFormat
    trust_level: TrustLevel
    coverage: tuple[str, ...]
    refresh_interval_days: int
    enabled: bool = True
    source_url: str | None = None
    publisher: str | None = None
    jurisdiction: str | None = None
    license_name: str | None = None
    license_url: str | None = None
    licensing_notes: str | None = None
    notes: str | None = None

    def validate(self) -> None:
        if not self.name.strip():
            raise SourceRegistryError("Source name must not be empty")

        if self.refresh_interval_days < 1:
            raise SourceRegistryError(
                f"{self.name}: refresh_interval_days must be at least 1"
            )

        if not self.coverage:
            raise SourceRegistryError(
                f"{self.name}: coverage must contain at least one jurisdiction"
            )

        normalized = [item.strip().upper() for item in self.coverage]

        if any(not item for item in normalized):
            raise SourceRegistryError(
                f"{self.name}: coverage contains an empty jurisdiction"
            )

        if len(set(normalized)) != len(normalized):
            raise SourceRegistryError(
                f"{self.name}: coverage contains duplicate jurisdictions"
            )

        for label, value in (
            ("source_url", self.source_url),
            ("license_url", self.license_url),
        ):
            if value is None:
                continue

            parsed = urlparse(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise SourceRegistryError(
                    f"{self.name}: {label} must be an absolute HTTP(S) URL"
                )

    def as_record(self) -> dict[str, object]:
        self.validate()
        return {
            "name": self.name,
            "source_type": self.source_type.value,
            "source_format": self.source_format.value,
            "trust_level": self.trust_level.value,
            "coverage": json.dumps(
                list(self.coverage),
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "refresh_interval_days": self.refresh_interval_days,
            "enabled": self.enabled,
            "source_url": self.source_url,
            "publisher": self.publisher,
            "jurisdiction": self.jurisdiction,
            "license_name": self.license_name,
            "license_url": self.license_url,
            "licensing_notes": self.licensing_notes,
            "notes": self.notes,
        }


def source_definition_from_mapping(
    payload: dict[str, object],
) -> SourceDefinition:
    required = {
        "name",
        "source_type",
        "source_format",
        "trust_level",
        "coverage",
        "refresh_interval_days",
    }

    missing = sorted(required - payload.keys())
    if missing:
        raise SourceRegistryError(
            "Missing required source fields: " + ", ".join(missing)
        )

    coverage_raw = payload["coverage"]
    if not isinstance(coverage_raw, list) or not all(
        isinstance(item, str) for item in coverage_raw
    ):
        raise SourceRegistryError("coverage must be a list of strings")

    try:
        definition = SourceDefinition(
            name=str(payload["name"]),
            source_type=SourceType(str(payload["source_type"])),
            source_format=SourceFormat(str(payload["source_format"])),
            trust_level=TrustLevel(str(payload["trust_level"])),
            coverage=tuple(coverage_raw),
            refresh_interval_days=int(payload["refresh_interval_days"]),
            enabled=bool(payload.get("enabled", True)),
            source_url=_optional_string(payload.get("source_url")),
            publisher=_optional_string(payload.get("publisher")),
            jurisdiction=_optional_string(payload.get("jurisdiction")),
            license_name=_optional_string(payload.get("license_name")),
            license_url=_optional_string(payload.get("license_url")),
            licensing_notes=_optional_string(payload.get("licensing_notes")),
            notes=_optional_string(payload.get("notes")),
        )
    except (TypeError, ValueError) as exc:
        raise SourceRegistryError(f"Invalid source registry value: {exc}") from exc

    definition.validate()
    return definition


def load_source_registry(path: Path) -> tuple[SourceDefinition, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SourceRegistryError(f"Source registry file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SourceRegistryError(f"Invalid source registry JSON: {exc}") from exc

    if not isinstance(payload, list):
        raise SourceRegistryError("Source registry root must be a JSON list")

    definitions = tuple(
        source_definition_from_mapping(item)
        for item in payload
        if isinstance(item, dict)
    )

    if len(definitions) != len(payload):
        raise SourceRegistryError("Every source registry entry must be a JSON object")

    names = [definition.name for definition in definitions]
    if len(set(names)) != len(names):
        raise SourceRegistryError("Source registry contains duplicate names")

    return tuple(sorted(definitions, key=lambda item: item.name.casefold()))


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SourceRegistryError("Optional text fields must be strings")
    stripped = value.strip()
    return stripped or None
