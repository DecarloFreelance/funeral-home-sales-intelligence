from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from canada_funeral_intel.collectors.import_execution import import_parsed_records
from canada_funeral_intel.collectors.importers import (
    ImportFormat,
    ImportRow,
    ImportRowError,
    ParseResult,
    payload_checksum,
)
from canada_funeral_intel.normalization.scalars import normalize_url
from canada_funeral_intel.storage.database import transaction
from canada_funeral_intel.verification.discovery import discover_website_candidates


class ManualWebsiteEvidenceError(ValueError):
    """Raised when manual website evidence cannot be safely imported."""


@dataclass(frozen=True, slots=True)
class ManualWebsiteEvidenceResult:
    import_run_id: int | None
    rows_seen: int
    rows_valid: int
    rows_failed: int
    candidates_inserted: int
    candidates_unchanged: int
    evidence_inserted: int
    review_entries_queued: int
    dry_run: bool


def export_manual_website_template(
    connection: sqlite3.Connection,
    *,
    output_path: Path,
    limit: int | None = None,
) -> dict[str, object]:
    if limit is not None and limit < 1:
        raise ManualWebsiteEvidenceError("limit must be positive")

    query = """
        SELECT
            e.id,
            COALESCE(
                e.canonical_name,
                MAX(CASE WHEN nv.field_name = 'business_name' THEN nv.normalized_value END)
            ) AS entity_name,
            MAX(CASE WHEN nv.field_name = 'city' THEN nv.normalized_value END) AS city,
            MAX(CASE WHEN nv.field_name = 'province' THEN nv.normalized_value END) AS province
        FROM entities AS e
        LEFT JOIN entity_source_records AS esr ON esr.entity_id = e.id
        LEFT JOIN normalized_values AS nv ON nv.source_record_id = esr.source_record_id
        WHERE e.status = 'active'
          AND NOT EXISTS (
              SELECT 1 FROM websites AS w
              WHERE w.entity_id = e.id AND w.status <> 'rejected'
          )
        GROUP BY e.id, e.canonical_name
        HAVING TRIM(COALESCE(
            e.canonical_name,
            MAX(CASE WHEN nv.field_name = 'business_name' THEN nv.normalized_value END)
        )) <> ''
        ORDER BY e.id
    """
    parameters: tuple[object, ...] = ()
    if limit is not None:
        query += " LIMIT ?"
        parameters = (limit,)
    rows = connection.execute(query, parameters).fetchall()
    try:
        with output_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(
                (
                    "entity_id",
                    "entity_name",
                    "city",
                    "province",
                    "website_url",
                    "source_url",
                    "note",
                )
            )
            for row in rows:
                writer.writerow(
                    (
                        row["id"],
                        _safe_csv_cell(row["entity_name"]),
                        _safe_csv_cell(row["city"]),
                        _safe_csv_cell(row["province"]),
                        "",
                        "",
                        "",
                    )
                )
    except OSError as exc:
        raise ManualWebsiteEvidenceError(
            f"Unable to write manual website template {output_path}: {exc}"
        ) from exc
    return {
        "output_path": str(output_path),
        "rows": len(rows),
        "network_used": False,
    }


def import_manual_website_evidence(
    connection: sqlite3.Connection,
    *,
    input_path: Path,
    source_dataset_id: int,
    dry_run: bool = False,
) -> ManualWebsiteEvidenceResult:
    records, parsed = _parse_file(connection, input_path)
    if dry_run:
        return ManualWebsiteEvidenceResult(
            import_run_id=None,
            rows_seen=parsed.records_seen,
            rows_valid=len(records),
            rows_failed=len(parsed.errors),
            candidates_inserted=0,
            candidates_unchanged=0,
            evidence_inserted=0,
            review_entries_queued=0,
            dry_run=True,
        )

    result = import_parsed_records(
        connection,
        source_dataset_id=source_dataset_id,
        input_path=input_path,
        input_format=ImportFormat.CSV,
        parsed=parsed,
        source_url="manual://website-evidence",
    )

    with transaction(connection):
        for record in records:
            source = connection.execute(
                """
                SELECT id
                FROM source_records
                WHERE source_dataset_id = ? AND external_record_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (source_dataset_id, record.external_record_id),
            ).fetchone()
            if source is None:
                raise ManualWebsiteEvidenceError(
                    f"Imported source record not found for row {record.row_number}"
                )
            source_record_id = int(source["id"])
            entity = connection.execute(
                "SELECT status FROM entities WHERE id = ?",
                (record.entity_id,),
            ).fetchone()
            if entity is None or entity["status"] != "active":
                raise ManualWebsiteEvidenceError(
                    f"Entity {record.entity_id} is not an active entity"
                )
            connection.execute(
                """
                INSERT OR IGNORE INTO entity_source_records
                    (entity_id, source_record_id, membership_role)
                VALUES (?, ?, 'location')
                """,
                (record.entity_id, source_record_id),
            )
            normalized = normalize_url(record.website_url)
            connection.execute(
                """
                INSERT INTO normalized_values (
                    source_record_id, field_name, original_value,
                    normalized_value, normalizer_name, normalizer_version,
                    normalized_at, warnings
                )
                SELECT ?, 'manual_website_url', ?, ?,
                       'normalize_url', 'url-v1', ?, '[]'
                WHERE NOT EXISTS (
                    SELECT 1 FROM normalized_values
                    WHERE source_record_id = ?
                      AND field_name = 'manual_website_url'
                      AND normalized_value = ?
                )
                """,
                (
                    source_record_id,
                    record.website_url,
                    normalized.value,
                    datetime.now(UTC).isoformat(),
                    source_record_id,
                    normalized.value,
                ),
            )

    discovered = discover_website_candidates(
        connection,
        source_dataset_id=source_dataset_id,
    )
    return ManualWebsiteEvidenceResult(
        import_run_id=result.import_run_id,
        rows_seen=parsed.records_seen,
        rows_valid=len(records),
        rows_failed=len(parsed.errors),
        candidates_inserted=discovered.candidates_inserted,
        candidates_unchanged=discovered.candidates_unchanged,
        evidence_inserted=discovered.evidence_inserted,
        review_entries_queued=discovered.review_entries_queued,
        dry_run=False,
    )


@dataclass(frozen=True, slots=True)
class _ManualRecord:
    row_number: int
    entity_id: int
    website_url: str
    external_record_id: str


def _parse_file(
    connection: sqlite3.Connection,
    path: Path,
) -> tuple[tuple[_ManualRecord, ...], ParseResult]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise ManualWebsiteEvidenceError("CSV input must contain a header row")
            required = {"entity_id", "website_url"}
            missing = sorted(required - set(reader.fieldnames))
            if missing:
                raise ManualWebsiteEvidenceError(
                    "CSV is missing required columns: " + ", ".join(missing)
                )
            rows: list[_ManualRecord] = []
            import_rows: list[ImportRow] = []
            errors: list[ImportRowError] = []
            for row_number, payload in enumerate(reader, start=2):
                raw_payload = json.dumps(
                    payload, ensure_ascii=False, separators=(",", ":"), sort_keys=False
                )
                try:
                    entity_id = int((payload.get("entity_id") or "").strip())
                    if entity_id < 1:
                        raise ValueError("entity_id must be positive")
                    website_url = (payload.get("website_url") or "").strip()
                    normalized = normalize_url(website_url)
                    if normalized.value is None:
                        raise ValueError("website_url could not be normalized")
                    if (
                        connection.execute(
                            "SELECT 1 FROM entities WHERE id = ? AND status = 'active'",
                            (entity_id,),
                        ).fetchone()
                        is None
                    ):
                        raise ValueError(f"active entity not found: {entity_id}")
                    external_id = f"entity-{entity_id}-url-{normalized.value}"
                except (ValueError, TypeError) as exc:
                    errors.append(ImportRowError(row_number, raw_payload, str(exc)))
                    continue
                rows.append(
                    _ManualRecord(row_number, entity_id, website_url, external_id)
                )
                import_rows.append(
                    ImportRow(
                        row_number,
                        raw_payload,
                        payload_checksum(raw_payload),
                        external_id,
                    )
                )
    except OSError as exc:
        raise ManualWebsiteEvidenceError(f"Unable to read {path}: {exc}") from exc
    return tuple(rows), ParseResult(tuple(import_rows), tuple(errors))


def _safe_csv_cell(value: object) -> str:
    text = "" if value is None else str(value)
    if text.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text
    return text
