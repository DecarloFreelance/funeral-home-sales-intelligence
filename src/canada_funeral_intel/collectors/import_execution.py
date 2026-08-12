from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from canada_funeral_intel.collectors.importers import (
    ImportFormat,
    ImportFrameworkError,
    ParseResult,
    parse_csv,
    parse_json,
)
from canada_funeral_intel.storage.database import transaction


@dataclass(frozen=True, slots=True)
class ImportExecutionResult:
    import_run_id: int
    records_seen: int
    records_inserted: int
    records_unchanged: int
    records_failed: int


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _parse_input(
    path: Path,
    input_format: ImportFormat,
    *,
    external_id_field: str | None,
) -> ParseResult:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ImportFrameworkError(f"Unable to read import file {path}: {exc}") from exc

    if input_format is ImportFormat.CSV:
        return parse_csv(text, external_id_field=external_id_field)
    if input_format is ImportFormat.JSON:
        return parse_json(text, external_id_field=external_id_field)

    raise ImportFrameworkError(f"Unsupported import format: {input_format}")


def import_file(
    connection: sqlite3.Connection,
    *,
    source_dataset_id: int,
    input_path: Path,
    input_format: ImportFormat,
    external_id_field: str | None = None,
    source_url: str | None = None,
    retrieved_at: str | None = None,
) -> ImportExecutionResult:
    parsed = _parse_input(
        input_path,
        input_format,
        external_id_field=external_id_field,
    )
    return import_parsed_records(
        connection,
        source_dataset_id=source_dataset_id,
        input_path=input_path,
        input_format=input_format,
        parsed=parsed,
        source_url=source_url,
        retrieved_at=retrieved_at,
    )


def import_parsed_records(
    connection: sqlite3.Connection,
    *,
    source_dataset_id: int,
    input_path: Path,
    input_format: ImportFormat,
    parsed: ParseResult,
    source_url: str | None = None,
    retrieved_at: str | None = None,
) -> ImportExecutionResult:
    if source_dataset_id < 1:
        raise ImportFrameworkError("source_dataset_id must be a positive integer")

    retrieved = retrieved_at or _utc_timestamp()
    started = _utc_timestamp()

    try:
        with transaction(connection):
            dataset = connection.execute(
                "SELECT id FROM source_datasets WHERE id = ?",
                (source_dataset_id,),
            ).fetchone()
            if dataset is None:
                raise ImportFrameworkError(
                    f"Source dataset does not exist: {source_dataset_id}"
                )

            cursor = connection.execute(
                """
                INSERT INTO import_runs (
                    source_dataset_id,
                    input_path,
                    input_format,
                    started_at,
                    status
                )
                VALUES (?, ?, ?, ?, 'running')
                """,
                (
                    source_dataset_id,
                    str(input_path),
                    input_format.value,
                    started,
                ),
            )
            import_run_id = int(cursor.lastrowid)

            inserted = 0
            unchanged = 0

            for row in parsed.rows:
                if _is_unchanged(
                    connection,
                    source_dataset_id=source_dataset_id,
                    external_record_id=row.external_record_id,
                    checksum=row.checksum,
                ):
                    unchanged += 1
                    continue

                connection.execute(
                    """
                    INSERT INTO source_records (
                        source_dataset_id,
                        external_record_id,
                        raw_payload,
                        payload_format,
                        source_url,
                        retrieved_at,
                        checksum,
                        import_run_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_dataset_id,
                        row.external_record_id,
                        row.raw_payload,
                        input_format.value,
                        source_url,
                        retrieved,
                        row.checksum,
                        import_run_id,
                    ),
                )
                inserted += 1

            for error in parsed.errors:
                connection.execute(
                    """
                    INSERT INTO import_run_errors (
                        import_run_id,
                        row_number,
                        external_record_id,
                        error_message,
                        raw_payload
                    )
                    VALUES (?, ?, NULL, ?, ?)
                    """,
                    (
                        import_run_id,
                        error.row_number,
                        error.message,
                        error.raw_payload,
                    ),
                )

            failed = len(parsed.errors)
            completed = _utc_timestamp()

            connection.execute(
                """
                UPDATE import_runs
                SET
                    completed_at = ?,
                    status = 'completed',
                    records_seen = ?,
                    records_inserted = ?,
                    records_unchanged = ?,
                    records_failed = ?
                WHERE id = ?
                """,
                (
                    completed,
                    parsed.records_seen,
                    inserted,
                    unchanged,
                    failed,
                    import_run_id,
                ),
            )

    except sqlite3.Error as exc:
        raise ImportFrameworkError(f"Database import failed: {exc}") from exc

    return ImportExecutionResult(
        import_run_id=import_run_id,
        records_seen=parsed.records_seen,
        records_inserted=inserted,
        records_unchanged=unchanged,
        records_failed=failed,
    )


def _is_unchanged(
    connection: sqlite3.Connection,
    *,
    source_dataset_id: int,
    external_record_id: str | None,
    checksum: str,
) -> bool:
    if external_record_id is None:
        row = connection.execute(
            """
            SELECT 1
            FROM source_records
            WHERE source_dataset_id = ?
              AND external_record_id IS NULL
              AND checksum = ?
            LIMIT 1
            """,
            (source_dataset_id, checksum),
        ).fetchone()
        return row is not None

    row = connection.execute(
        """
        SELECT checksum
        FROM source_records
        WHERE source_dataset_id = ?
          AND external_record_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (source_dataset_id, external_record_id),
    ).fetchone()

    return row is not None and row["checksum"] == checksum
