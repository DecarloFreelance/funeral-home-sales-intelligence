from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime


class NormalizationError(ValueError):
    """Raised when normalization metadata is invalid."""


@dataclass(frozen=True, slots=True)
class NormalizedValue:
    source_record_id: int
    field_name: str
    original_value: str | None
    normalized_value: str | None
    normalizer_name: str
    normalizer_version: str
    normalized_at: str
    warnings: tuple[str, ...] = ()

    def validate(self) -> None:
        if self.source_record_id < 1:
            raise NormalizationError("source_record_id must be a positive integer")
        if not self.field_name.strip():
            raise NormalizationError("field_name must not be empty")
        if not self.normalizer_name.strip():
            raise NormalizationError("normalizer_name must not be empty")
        if not self.normalizer_version.strip():
            raise NormalizationError("normalizer_version must not be empty")
        if not self.normalized_at.strip():
            raise NormalizationError("normalized_at must not be empty")
        if any(not warning.strip() for warning in self.warnings):
            raise NormalizationError("warnings must not contain empty values")

    def as_record(self) -> dict[str, object]:
        self.validate()
        return {
            "source_record_id": self.source_record_id,
            "field_name": self.field_name,
            "original_value": self.original_value,
            "normalized_value": self.normalized_value,
            "normalizer_name": self.normalizer_name,
            "normalizer_version": self.normalizer_version,
            "normalized_at": self.normalized_at,
            "warnings": json.dumps(
                list(self.warnings),
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        }


def normalization_timestamp() -> str:
    return datetime.now(UTC).isoformat()


def make_normalized_value(
    *,
    source_record_id: int,
    field_name: str,
    original_value: str | None,
    normalized_value: str | None,
    normalizer_name: str,
    normalizer_version: str,
    warnings: tuple[str, ...] = (),
    normalized_at: str | None = None,
) -> NormalizedValue:
    value = NormalizedValue(
        source_record_id=source_record_id,
        field_name=field_name,
        original_value=original_value,
        normalized_value=normalized_value,
        normalizer_name=normalizer_name,
        normalizer_version=normalizer_version,
        normalized_at=normalized_at or normalization_timestamp(),
        warnings=warnings,
    )
    value.validate()
    return value
