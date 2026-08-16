from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from canada_funeral_intel.collectors.import_execution import import_file
from canada_funeral_intel.collectors.importers import (
    ImportFormat,
    parse_csv,
    parse_json,
)
from canada_funeral_intel.deduplication.deterministic import (
    generate_deterministic_matches,
)
from canada_funeral_intel.deduplication.entity_materialization import (
    materialize_source_record_entities,
)
from canada_funeral_intel.deduplication.fuzzy import generate_fuzzy_matches
from canada_funeral_intel.deduplication.review import populate_review_queue
from canada_funeral_intel.normalization.execution import normalize_source_records
from canada_funeral_intel.storage.database import transaction

from . import PIPELINE_VERSION, STAGES


class PipelineError(RuntimeError):
    """Raised when an offline pipeline run cannot proceed safely."""


@dataclass(frozen=True, slots=True)
class PipelineInput:
    source_dataset_id: int
    input_path: Path
    input_format: ImportFormat
    external_id_field: str | None = None
    through_stage: str = "materialize"
    skip_fuzzy: bool = False


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _fingerprint(spec: PipelineInput) -> str:
    try:
        content = spec.input_path.read_bytes()
    except OSError as exc:
        raise PipelineError(
            f"Unable to read pipeline input {spec.input_path}: {exc}"
        ) from exc
    payload = {
        "pipeline_version": PIPELINE_VERSION,
        "source_dataset_id": spec.source_dataset_id,
        "input_format": spec.input_format.value,
        "external_id_field": spec.external_id_field,
        "through_stage": spec.through_stage,
        "skip_fuzzy": spec.skip_fuzzy,
        "content_sha256": hashlib.sha256(content).hexdigest(),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _validate_spec(spec: PipelineInput) -> None:
    if spec.source_dataset_id < 1:
        raise PipelineError("source_dataset_id must be positive")
    if spec.through_stage not in STAGES:
        raise PipelineError(f"unknown pipeline stage: {spec.through_stage}")
    if not spec.input_path.is_file():
        raise PipelineError(f"pipeline input does not exist: {spec.input_path}")


def _stage_names(through_stage: str) -> list[str]:
    return list(STAGES[: STAGES.index(through_stage) + 1])


def create_run(
    connection: sqlite3.Connection, spec: PipelineInput, *, dry_run: bool = False
) -> dict[str, object]:
    _validate_spec(spec)
    if (
        connection.execute(
            "SELECT 1 FROM source_datasets WHERE id = ?", (spec.source_dataset_id,)
        ).fetchone()
        is None
    ):
        raise PipelineError(f"source dataset does not exist: {spec.source_dataset_id}")
    fingerprint = _fingerprint(spec)
    if dry_run:
        parsed = _parse(spec)
        return {
            "pipeline_version": PIPELINE_VERSION,
            "dry_run": True,
            "run_id": None,
            "input_fingerprint": fingerprint,
            "stages": _dry_stages(spec, parsed.records_seen, len(parsed.errors)),
            "projected_import": {
                "records_seen": parsed.records_seen,
                "records_failed": len(parsed.errors),
            },
        }
    with transaction(connection):
        cursor = connection.execute(
            """INSERT INTO pipeline_runs
            (pipeline_version, source_dataset_id, input_path, input_format, external_id_field,
             input_fingerprint, through_stage, skip_fuzzy, status, started_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'running', ?)""",
            (
                PIPELINE_VERSION,
                spec.source_dataset_id,
                str(spec.input_path),
                spec.input_format.value,
                spec.external_id_field,
                fingerprint,
                spec.through_stage,
                int(spec.skip_fuzzy),
                _now(),
            ),
        )
        run_id = int(cursor.lastrowid)
        for ordinal, stage in enumerate(_stage_names(spec.through_stage), 1):
            status = (
                "skipped" if stage == "fuzzy_match" and spec.skip_fuzzy else "pending"
            )
            connection.execute(
                "INSERT INTO pipeline_run_stages (pipeline_run_id, stage_name, ordinal, status) VALUES (?, ?, ?, ?)",
                (run_id, stage, ordinal, status),
            )
    return execute_run(connection, run_id)


def resume_run(connection: sqlite3.Connection, run_id: int) -> dict[str, object]:
    if run_id < 1:
        raise PipelineError("run_id must be positive")
    row = connection.execute(
        "SELECT * FROM pipeline_runs WHERE id = ?", (run_id,)
    ).fetchone()
    if row is None:
        raise PipelineError(f"pipeline run not found: {run_id}")
    if row["status"] not in {"failed", "cancelled"}:
        raise PipelineError(
            f"pipeline run {run_id} cannot be resumed from {row['status']}"
        )
    spec = PipelineInput(
        source_dataset_id=int(row["source_dataset_id"]),
        input_path=Path(str(row["input_path"])),
        input_format=ImportFormat(str(row["input_format"])),
        external_id_field=row["external_id_field"],
        through_stage=str(row["through_stage"]),
        skip_fuzzy=bool(row["skip_fuzzy"]),
    )
    _validate_spec(spec)
    if _fingerprint(spec) != str(row["input_fingerprint"]):
        raise PipelineError("pipeline input or configuration changed; resume rejected")
    with transaction(connection):
        changed = connection.execute(
            "UPDATE pipeline_runs SET status='running', started_at=?, failed_at=NULL, error_summary=NULL, updated_at=? WHERE id=? AND status IN ('failed','cancelled')",
            (_now(), _now(), run_id),
        ).rowcount
        if changed != 1:
            raise PipelineError("pipeline run is already being resumed")
    return execute_run(connection, run_id)


def execute_run(connection: sqlite3.Connection, run_id: int) -> dict[str, object]:
    run = connection.execute(
        "SELECT * FROM pipeline_runs WHERE id = ?", (run_id,)
    ).fetchone()
    if run is None:
        raise PipelineError(f"pipeline run not found: {run_id}")
    stages = connection.execute(
        "SELECT * FROM pipeline_run_stages WHERE pipeline_run_id = ? ORDER BY ordinal",
        (run_id,),
    ).fetchall()
    spec = PipelineInput(
        int(run["source_dataset_id"]),
        Path(str(run["input_path"])),
        ImportFormat(str(run["input_format"])),
        run["external_id_field"],
        str(run["through_stage"]),
        bool(run["skip_fuzzy"]),
    )
    try:
        for stage in stages:
            if stage["status"] in {"completed", "skipped"}:
                continue
            _run_stage(
                connection, run_id, int(stage["id"]), str(stage["stage_name"]), spec
            )
        with transaction(connection):
            connection.execute(
                "UPDATE pipeline_runs SET status='completed', completed_at=?, updated_at=? WHERE id=? AND status='running'",
                (_now(), _now(), run_id),
            )
    except Exception as exc:
        _fail(connection, run_id, str(exc))
        raise
    return show_run(connection, run_id)


def _run_stage(
    connection: sqlite3.Connection,
    run_id: int,
    stage_id: int,
    stage: str,
    spec: PipelineInput,
) -> None:
    with transaction(connection):
        changed = connection.execute(
            "UPDATE pipeline_run_stages SET status='running', attempt_count=attempt_count+1, started_at=? WHERE id=? AND (status='pending' OR status='failed')",
            (_now(), stage_id),
        ).rowcount
        if changed != 1:
            raise PipelineError(f"stage {stage} is not available for execution")
    try:
        result = _execute_stage(connection, stage, spec)
        values = {
            name: int(result.get(name, 0))
            for name in (
                "input_count",
                "processed_count",
                "inserted_count",
                "updated_count",
                "unchanged_count",
                "skipped_count",
                "review_count",
                "error_count",
            )
        }
        with transaction(connection):
            connection.execute(
                """UPDATE pipeline_run_stages SET status='completed', completed_at=?, input_count=?, processed_count=?, inserted_count=?, updated_count=?, unchanged_count=?, skipped_count=?, review_count=?, error_count=? WHERE id=? AND status='running'""",
                (
                    _now(),
                    values["input_count"],
                    values["processed_count"],
                    values["inserted_count"],
                    values["updated_count"],
                    values["unchanged_count"],
                    values["skipped_count"],
                    values["review_count"],
                    values["error_count"],
                    stage_id,
                ),
            )
    except Exception as exc:
        with transaction(connection):
            connection.execute(
                "UPDATE pipeline_run_stages SET status='failed', completed_at=?, error_count=error_count+1 WHERE id=? AND status='running'",
                (_now(), stage_id),
            )
            connection.execute(
                "INSERT INTO pipeline_run_errors (pipeline_run_id, pipeline_run_stage_id, error_message) VALUES (?, ?, ?)",
                (run_id, stage_id, str(exc)[:1000]),
            )
        if isinstance(exc, PipelineError):
            raise
        raise PipelineError(str(exc)) from exc


def _execute_stage(
    connection: sqlite3.Connection, stage: str, spec: PipelineInput
) -> dict[str, int]:
    if stage == "import":
        result = import_file(
            connection,
            source_dataset_id=spec.source_dataset_id,
            input_path=spec.input_path,
            input_format=spec.input_format,
            external_id_field=spec.external_id_field,
        )
        return {
            "input_count": result.records_seen,
            "processed_count": result.records_seen,
            "inserted_count": result.records_inserted,
            "unchanged_count": result.records_unchanged,
            "error_count": result.records_failed,
        }
    if stage == "normalize":
        result = normalize_source_records(
            connection, source_dataset_id=spec.source_dataset_id
        )
        return {
            "input_count": result.records_seen,
            "processed_count": result.records_seen,
            "inserted_count": result.values_inserted,
            "unchanged_count": result.values_unchanged,
            "skipped_count": result.fields_skipped,
        }
    if stage == "deterministic_match":
        result = generate_deterministic_matches(connection)
        return {
            "input_count": result.records_seen,
            "processed_count": result.pairs_found,
            "inserted_count": result.candidates_inserted,
            "unchanged_count": result.candidates_unchanged,
            "updated_count": result.evidence_inserted,
        }
    if stage == "fuzzy_match":
        result = generate_fuzzy_matches(connection)
        return {
            "input_count": result.records_seen,
            "processed_count": result.pairs_scored,
            "inserted_count": result.candidates_inserted,
            "unchanged_count": result.candidates_unchanged,
            "updated_count": result.evidence_inserted,
            "skipped_count": result.blocked_pairs,
        }
    if stage == "review_queue":
        result = populate_review_queue(connection)
        return {
            "input_count": result.review_candidates_seen,
            "processed_count": result.review_candidates_seen,
            "inserted_count": result.queue_entries_inserted,
            "unchanged_count": result.queue_entries_unchanged,
            "review_count": result.review_candidates_seen,
        }
    if stage == "materialize":
        result = materialize_source_record_entities(connection)
        return {
            "input_count": result.source_records_seen,
            "processed_count": result.source_records_seen,
            "inserted_count": result.entities_inserted + result.memberships_inserted,
            "unchanged_count": result.records_unchanged,
        }
    raise PipelineError(f"unknown pipeline stage: {stage}")


def _fail(connection: sqlite3.Connection, run_id: int, message: str) -> None:
    with transaction(connection):
        connection.execute(
            "UPDATE pipeline_runs SET status='failed', failed_at=?, error_summary=?, updated_at=? WHERE id=? AND status='running'",
            (_now(), message[:1000], _now(), run_id),
        )


def _parse(spec: PipelineInput):
    text = spec.input_path.read_text(encoding="utf-8")
    return (
        parse_csv(text, external_id_field=spec.external_id_field)
        if spec.input_format is ImportFormat.CSV
        else parse_json(text, external_id_field=spec.external_id_field)
    )


def _dry_stages(
    spec: PipelineInput, records: int, errors: int
) -> list[dict[str, object]]:
    result = []
    for stage in _stage_names(spec.through_stage):
        result.append(
            {
                "stage_name": stage,
                "status": "skipped"
                if stage == "fuzzy_match" and spec.skip_fuzzy
                else "projected",
                "input_count": records if stage == "import" else None,
                "error_count": errors if stage == "import" else None,
            }
        )
    return result


def show_run(connection: sqlite3.Connection, run_id: int) -> dict[str, object]:
    row = connection.execute(
        "SELECT * FROM pipeline_runs WHERE id = ?", (run_id,)
    ).fetchone()
    if row is None:
        raise PipelineError(f"pipeline run not found: {run_id}")
    stages = [
        dict(item)
        for item in connection.execute(
            "SELECT * FROM pipeline_run_stages WHERE pipeline_run_id=? ORDER BY ordinal",
            (run_id,),
        ).fetchall()
    ]
    errors = [
        dict(item)
        for item in connection.execute(
            "SELECT * FROM pipeline_run_errors WHERE pipeline_run_id=? ORDER BY id",
            (run_id,),
        ).fetchall()
    ]
    payload = dict(row)
    payload["run_id"] = int(row["id"])
    payload["dry_run"] = False
    payload["stages"] = stages
    payload["errors"] = errors
    return payload


def list_runs(
    connection: sqlite3.Connection,
    *,
    status: str | None = None,
    limit: int | None = None,
) -> list[dict[str, object]]:
    query = "SELECT id, pipeline_version, source_dataset_id, input_path, input_fingerprint, through_stage, skip_fuzzy, status, started_at, completed_at, failed_at, resumed_from_run_id, created_at FROM pipeline_runs"
    params: list[object] = []
    if status:
        query += " WHERE status = ?"
        params.append(status)
    query += " ORDER BY created_at DESC, id DESC"
    if limit is not None:
        if limit < 1:
            raise PipelineError("limit must be positive")
        query += " LIMIT ?"
        params.append(limit)
    return [dict(row) for row in connection.execute(query, params).fetchall()]


def list_stages(connection: sqlite3.Connection, run_id: int) -> list[dict[str, object]]:
    if (
        connection.execute(
            "SELECT 1 FROM pipeline_runs WHERE id=?", (run_id,)
        ).fetchone()
        is None
    ):
        raise PipelineError(f"pipeline run not found: {run_id}")
    return [
        dict(row)
        for row in connection.execute(
            "SELECT * FROM pipeline_run_stages WHERE pipeline_run_id=? ORDER BY ordinal",
            (run_id,),
        ).fetchall()
    ]
