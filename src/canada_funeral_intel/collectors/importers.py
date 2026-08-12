from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from enum import StrEnum


class ImportFrameworkError(ValueError):
    """Raised when an input dataset cannot be parsed safely."""


class ImportFormat(StrEnum):
    CSV = "csv"
    JSON = "json"


@dataclass(frozen=True, slots=True)
class ImportRow:
    row_number: int
    raw_payload: str
    checksum: str
    external_record_id: str | None


@dataclass(frozen=True, slots=True)
class ImportRowError:
    row_number: int
    raw_payload: str | None
    message: str


@dataclass(frozen=True, slots=True)
class ParseResult:
    rows: tuple[ImportRow, ...]
    errors: tuple[ImportRowError, ...]

    @property
    def records_seen(self) -> int:
        return len(self.rows) + len(self.errors)


def payload_checksum(raw_payload: str) -> str:
    return hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()


def parse_csv(
    text: str,
    *,
    external_id_field: str | None = None,
) -> ParseResult:
    stream = io.StringIO(text, newline="")
    reader = csv.DictReader(stream)

    if reader.fieldnames is None:
        raise ImportFrameworkError("CSV input must contain a header row")

    fieldnames = tuple(reader.fieldnames)
    if any(name is None or not name for name in fieldnames):
        raise ImportFrameworkError("CSV header names must not be empty")
    if len(set(fieldnames)) != len(fieldnames):
        raise ImportFrameworkError("CSV header names must be unique")

    rows: list[ImportRow] = []
    errors: list[ImportRowError] = []

    for row_number, payload in enumerate(reader, start=2):
        if None in payload:
            errors.append(
                ImportRowError(
                    row_number=row_number,
                    raw_payload=_serialize_payload(payload),
                    message="CSV row contains more values than the header",
                )
            )
            continue

        raw_payload = _serialize_payload(payload)
        try:
            external_id = _external_id(payload, external_id_field)
        except ImportFrameworkError as exc:
            errors.append(
                ImportRowError(
                    row_number=row_number,
                    raw_payload=raw_payload,
                    message=str(exc),
                )
            )
            continue

        rows.append(
            ImportRow(
                row_number=row_number,
                raw_payload=raw_payload,
                checksum=payload_checksum(raw_payload),
                external_record_id=external_id,
            )
        )

    return ParseResult(rows=tuple(rows), errors=tuple(errors))


def parse_json(
    text: str,
    *,
    external_id_field: str | None = None,
) -> ParseResult:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ImportFrameworkError(f"Invalid JSON input: {exc}") from exc

    if not isinstance(payload, list):
        raise ImportFrameworkError("JSON input must contain a top-level list")

    rows: list[ImportRow] = []
    errors: list[ImportRowError] = []

    for row_number, item in enumerate(payload, start=1):
        raw_payload = _serialize_payload(item)

        if not isinstance(item, dict):
            errors.append(
                ImportRowError(
                    row_number=row_number,
                    raw_payload=raw_payload,
                    message="JSON record must be an object",
                )
            )
            continue

        try:
            external_id = _external_id(item, external_id_field)
        except ImportFrameworkError as exc:
            errors.append(
                ImportRowError(
                    row_number=row_number,
                    raw_payload=raw_payload,
                    message=str(exc),
                )
            )
            continue

        rows.append(
            ImportRow(
                row_number=row_number,
                raw_payload=raw_payload,
                checksum=payload_checksum(raw_payload),
                external_record_id=external_id,
            )
        )

    return ParseResult(rows=tuple(rows), errors=tuple(errors))


def _external_id(
    payload: dict[object, object],
    field: str | None,
) -> str | None:
    if field is None:
        return None

    value = payload.get(field)
    if value is None or value == "":
        return None
    if isinstance(value, (str, int, float, bool)):
        return str(value)

    raise ImportFrameworkError(
        f"External record ID field {field!r} must contain a scalar value"
    )


def _serialize_payload(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=False,
    )
