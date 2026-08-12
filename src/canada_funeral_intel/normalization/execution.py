from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from canada_funeral_intel.normalization.addresses import normalize_address
from canada_funeral_intel.normalization.business_names import normalize_business_name
from canada_funeral_intel.normalization.models import (
    NormalizedValue,
    make_normalized_value,
)
from canada_funeral_intel.normalization.scalars import (
    ScalarNormalization,
    normalize_city,
    normalize_domain,
    normalize_email,
    normalize_phone,
    normalize_postal_code,
    normalize_province,
    normalize_url,
)
from canada_funeral_intel.storage.database import transaction

_NORMALIZER_VERSION = "1"

_NORMALIZER_VERSIONS = {
    "phone": "2",
}


def _normalizer_version(field_name: str) -> str:
    return _NORMALIZER_VERSIONS.get(
        field_name,
        _NORMALIZER_VERSION,
    )


_FIELD_ALIASES = {
    "name": "business_name",
    "business_name": "business_name",
    "funeral_home_name": "business_name",
    "organization_name": "business_name",
    "parent_organization": "parent_organization",
    "parent_organization_name": "parent_organization",
    "parent_company": "parent_organization",
    "parent_company_name": "parent_organization",
    "address": "address",
    "address1": "address",
    "street_address": "address",
    "street": "address",
    "city": "city",
    "municipality": "city",
    "town": "city",
    "province": "province",
    "province_code": "province",
    "postal": "postal_code",
    "postal_code": "postal_code",
    "postcode": "postal_code",
    "phone": "phone",
    "telephone": "phone",
    "phone_number": "phone",
    "email": "email",
    "email_address": "email",
    "url": "url",
    "website": "url",
    "website_url": "url",
    "official_website": "explicit_website_url",
    "official_website_url": "explicit_website_url",
    "homepage": "explicit_website_url",
    "home_page": "explicit_website_url",
    "organization_website": "explicit_website_url",
    "organization_url": "explicit_website_url",
    "contact_url": "explicit_website_url",
    "domain": "domain",
    "official_domain": "explicit_website_domain",
    "organization_domain": "explicit_website_domain",
}


class NormalizationExecutionError(RuntimeError):
    """Raised when source records cannot be normalized safely."""


@dataclass(frozen=True, slots=True)
class NormalizationExecutionResult:
    records_seen: int
    values_inserted: int
    values_unchanged: int
    fields_skipped: int


def normalize_source_records(
    connection: sqlite3.Connection,
    *,
    source_dataset_id: int | None = None,
) -> NormalizationExecutionResult:
    if source_dataset_id is not None and source_dataset_id < 1:
        raise NormalizationExecutionError(
            "source_dataset_id must be a positive integer"
        )

    query = """
        SELECT id, source_dataset_id, raw_payload
        FROM source_records
    """
    parameters: tuple[object, ...] = ()
    if source_dataset_id is not None:
        query += " WHERE source_dataset_id = ?"
        parameters = (source_dataset_id,)
    query += " ORDER BY id"

    rows = connection.execute(query, parameters).fetchall()

    records_seen = 0
    inserted = 0
    unchanged = 0
    skipped = 0

    try:
        with transaction(connection):
            for row in rows:
                records_seen += 1
                source_record_id = int(row["id"])
                payload = _load_payload(
                    source_record_id,
                    str(row["raw_payload"]),
                )

                for source_field, raw_value in payload.items():
                    canonical_field = _FIELD_ALIASES.get(source_field.casefold())
                    if canonical_field is None:
                        skipped += 1
                        continue

                    original_value = _scalar_text(raw_value)
                    if raw_value is not None and original_value is None:
                        skipped += 1
                        continue

                    normalized = _normalize_field(
                        source_record_id=source_record_id,
                        field_name=canonical_field,
                        original_value=original_value,
                    )

                    if _already_normalized(connection, normalized):
                        unchanged += 1
                        continue

                    record = normalized.as_record()
                    connection.execute(
                        """
                        INSERT INTO normalized_values (
                            source_record_id,
                            field_name,
                            original_value,
                            normalized_value,
                            normalizer_name,
                            normalizer_version,
                            normalized_at,
                            warnings
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            record["source_record_id"],
                            record["field_name"],
                            record["original_value"],
                            record["normalized_value"],
                            record["normalizer_name"],
                            record["normalizer_version"],
                            record["normalized_at"],
                            record["warnings"],
                        ),
                    )
                    inserted += 1
    except sqlite3.Error as exc:
        raise NormalizationExecutionError(
            f"Database normalization failed: {exc}"
        ) from exc

    return NormalizationExecutionResult(
        records_seen=records_seen,
        values_inserted=inserted,
        values_unchanged=unchanged,
        fields_skipped=skipped,
    )


def _load_payload(source_record_id: int, raw_payload: str) -> dict[str, object]:
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError as exc:
        raise NormalizationExecutionError(
            f"Source record {source_record_id} contains invalid JSON"
        ) from exc

    if not isinstance(payload, dict):
        raise NormalizationExecutionError(
            f"Source record {source_record_id} payload must be a JSON object"
        )

    if not all(isinstance(key, str) for key in payload):
        raise NormalizationExecutionError(
            f"Source record {source_record_id} contains a non-string field name"
        )

    return payload


def _scalar_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    return None


def _normalize_field(
    *,
    source_record_id: int,
    field_name: str,
    original_value: str | None,
) -> NormalizedValue:
    if field_name in {"business_name", "parent_organization"}:
        result = normalize_business_name(original_value)
        return make_normalized_value(
            source_record_id=source_record_id,
            field_name=field_name,
            original_value=original_value,
            normalized_value=result.comparison_key,
            normalizer_name=field_name,
            normalizer_version=_normalizer_version(field_name),
            warnings=result.warnings,
        )

    if field_name == "address":
        result = normalize_address(original_value)
        return make_normalized_value(
            source_record_id=source_record_id,
            field_name=field_name,
            original_value=original_value,
            normalized_value=result.comparison_key,
            normalizer_name="address",
            normalizer_version=_normalizer_version(field_name),
            warnings=result.warnings,
        )

    normalizers: dict[str, Callable[[str | None], ScalarNormalization]] = {
        "city": normalize_city,
        "province": normalize_province,
        "postal_code": normalize_postal_code,
        "phone": normalize_phone,
        "email": normalize_email,
        "url": normalize_url,
        "domain": normalize_domain,
        "explicit_website_url": normalize_url,
        "explicit_website_domain": normalize_domain,
    }
    normalizer = normalizers[field_name]
    result = normalizer(original_value)
    return make_normalized_value(
        source_record_id=source_record_id,
        field_name=field_name,
        original_value=original_value,
        normalized_value=result.value,
        normalizer_name=field_name,
        normalizer_version=_normalizer_version(field_name),
        warnings=result.warnings,
    )


def _already_normalized(
    connection: sqlite3.Connection,
    value: NormalizedValue,
) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM normalized_values
        WHERE source_record_id = ?
          AND field_name = ?
          AND normalizer_name = ?
          AND normalizer_version = ?
        LIMIT 1
        """,
        (
            value.source_record_id,
            value.field_name,
            value.normalizer_name,
            value.normalizer_version,
        ),
    ).fetchone()
    return row is not None
