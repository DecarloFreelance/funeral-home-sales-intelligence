from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from canada_funeral_intel.storage.database import transaction

from .models import RefreshObservation

RUN_TYPES = ("website_page", "person_observation", "business_fact")
RUN_STATUSES = ("running", "completed", "failed", "cancelled")
CHANGE_TYPES = ("added", "changed", "missing", "reappeared")


def _utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("reference time must include a timezone")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def begin_run(connection: sqlite3.Connection, *, run_type: str, scope_type: str, scope_value: str | None, reference_time: datetime, extractor_version: str | None = None, config_fingerprint: str | None = None) -> int:
    if run_type not in RUN_TYPES or not scope_type.strip():
        raise ValueError("invalid refresh scope")
    try:
        with transaction(connection):
            row = connection.execute("INSERT INTO refresh_runs (run_type, scope_type, scope_value, reference_time, status, extractor_version, config_fingerprint) VALUES (?, ?, ?, ?, 'running', ?, ?) RETURNING id", (run_type, scope_type.strip(), scope_value, _utc(reference_time), extractor_version, config_fingerprint)).fetchone()
        return int(row["id"])
    except sqlite3.IntegrityError as exc:
        raise ValueError("refresh run already exists for this scope and reference time") from exc


def record_observation(connection: sqlite3.Connection, *, run_id: int, observation: RefreshObservation) -> dict[str, object]:
    if observation.subject_type not in RUN_TYPES or not observation.subject_key.strip() or len(observation.semantic_fingerprint) != 64:
        raise ValueError("invalid refresh observation")
    try:
        json.loads(observation.metadata_json)
        with transaction(connection):
            run = connection.execute("SELECT status FROM refresh_runs WHERE id = ?", (run_id,)).fetchone()
            if run is None or run["status"] != "running":
                raise ValueError("refresh run is not running")
            existing = connection.execute("SELECT semantic_fingerprint, reference_id, metadata_json FROM refresh_run_items WHERE refresh_run_id = ? AND subject_type = ? AND subject_key = ?", (run_id, observation.subject_type, observation.subject_key)).fetchone()
            if existing is not None:
                if existing["semantic_fingerprint"] != observation.semantic_fingerprint or existing["reference_id"] != observation.reference_id or existing["metadata_json"] != observation.metadata_json:
                    raise ValueError("conflicting duplicate refresh observation")
                return {"status": "unchanged", "item_id": None}
            row = connection.execute("INSERT INTO refresh_run_items (refresh_run_id, subject_type, subject_key, semantic_fingerprint, reference_id, present, metadata_json) VALUES (?, ?, ?, ?, ?, 1, ?) RETURNING id", (run_id, observation.subject_type, observation.subject_key, observation.semantic_fingerprint, observation.reference_id, observation.metadata_json)).fetchone()
        return {"status": "inserted", "item_id": int(row["id"])}
    except json.JSONDecodeError as exc:
        raise ValueError("metadata_json must be valid JSON") from exc


def complete_run(connection: sqlite3.Connection, run_id: int) -> dict[str, int | str]:
    with transaction(connection):
        run = connection.execute("SELECT * FROM refresh_runs WHERE id = ?", (run_id,)).fetchone()
        if run is None or run["status"] != "running":
            raise ValueError("refresh run is not running")
        previous = connection.execute("SELECT id FROM refresh_runs WHERE run_type = ? AND scope_type = ? AND scope_value IS ? AND status = 'completed' AND id < ? ORDER BY id DESC LIMIT 1", (run["run_type"], run["scope_type"], run["scope_value"], run_id)).fetchone()
        previous_id = None if previous is None else int(previous["id"])
        current = {str(row["subject_type"]) + "\x00" + str(row["subject_key"]): dict(row) for row in connection.execute("SELECT * FROM refresh_run_items WHERE refresh_run_id = ?", (run_id,)).fetchall()}
        prior_rows = [] if previous_id is None else [dict(row) for row in connection.execute("SELECT * FROM refresh_run_items WHERE refresh_run_id = ?", (previous_id,)).fetchall()]
        prior = {str(row["subject_type"]) + "\x00" + str(row["subject_key"]): row for row in prior_rows}
        events = 0
        for key, row in current.items():
            old = prior.get(key)
            if old is None:
                change = "added"
            elif old["present"] == 0:
                change = "reappeared"
            elif old["semantic_fingerprint"] == row["semantic_fingerprint"]:
                continue
            else:
                change = "changed"
            connection.execute("INSERT OR IGNORE INTO change_events (refresh_run_id, subject_type, subject_key, change_type, previous_fingerprint, current_fingerprint, previous_reference_id, current_reference_id, reason_code, metadata_json, detected_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (run_id, row["subject_type"], row["subject_key"], change, None if old is None else old["semantic_fingerprint"], row["semantic_fingerprint"], None if old is None else old["reference_id"], row["reference_id"], f"{change}_observation", row["metadata_json"], run["reference_time"]))
            events += 1
        current_keys = set(current)
        for key, old in prior.items():
            if key in current_keys or old["present"] == 0: continue
            connection.execute("INSERT INTO refresh_run_items (refresh_run_id, subject_type, subject_key, semantic_fingerprint, reference_id, present, metadata_json) VALUES (?, ?, ?, ?, ?, 0, ?)", (run_id, old["subject_type"], old["subject_key"], old["semantic_fingerprint"], old["reference_id"], old["metadata_json"]))
            connection.execute("INSERT OR IGNORE INTO change_events (refresh_run_id, subject_type, subject_key, change_type, previous_fingerprint, previous_reference_id, reason_code, metadata_json, detected_at) VALUES (?, ?, ?, 'missing', ?, ?, 'single_refresh_absence', ?, ?)", (run_id, old["subject_type"], old["subject_key"], old["semantic_fingerprint"], old["reference_id"], old["metadata_json"], run["reference_time"]))
            events += 1
        connection.execute("UPDATE refresh_runs SET status='completed', completed_at=? WHERE id=?", (run["reference_time"], run_id))
    return {"run_id": run_id, "previous_run_id": previous_id, "events": events, "status": "completed"}


def fail_run(connection: sqlite3.Connection, *, run_id: int, error_summary: str, status: str = "failed") -> dict[str, object]:
    if status not in ("failed", "cancelled") or not error_summary.strip():
        raise ValueError("invalid failed refresh state")
    with transaction(connection):
        row = connection.execute("SELECT status FROM refresh_runs WHERE id=?", (run_id,)).fetchone()
        if row is None or row["status"] != "running": raise ValueError("refresh run is not running")
        connection.execute("UPDATE refresh_runs SET status=?, error_summary=?, completed_at=started_at WHERE id=?", (status, error_summary.strip(), run_id))
    return {"run_id": run_id, "status": status}


def list_runs(connection: sqlite3.Connection, *, run_type: str | None = None, status: str | None = None) -> list[dict[str, object]]:
    conditions, params = [], []
    if run_type: conditions.append("run_type=?"); params.append(run_type)
    if status: conditions.append("status=?"); params.append(status)
    query = "SELECT * FROM refresh_runs" + (" WHERE " + " AND ".join(conditions) if conditions else "") + " ORDER BY id"
    return [dict(row) for row in connection.execute(query, params).fetchall()]


def list_changes(connection: sqlite3.Connection, *, subject_type: str | None = None, subject_key: str | None = None, run_id: int | None = None, change_type: str | None = None) -> list[dict[str, object]]:
    conditions, params = [], []
    for column, value in (("subject_type", subject_type), ("subject_key", subject_key), ("refresh_run_id", run_id), ("change_type", change_type)):
        if value is not None: conditions.append(f"{column}=?"); params.append(value)
    query = "SELECT * FROM change_events" + (" WHERE " + " AND ".join(conditions) if conditions else "") + " ORDER BY refresh_run_id, subject_type, subject_key, id"
    return [dict(row) for row in connection.execute(query, params).fetchall()]


def show_run(connection: sqlite3.Connection, run_id: int) -> dict[str, object]:
    row = connection.execute("SELECT * FROM refresh_runs WHERE id=?", (run_id,)).fetchone()
    if row is None: raise ValueError(f"Refresh run not found: {run_id}")
    result = dict(row)
    result["items"] = [dict(item) for item in connection.execute("SELECT * FROM refresh_run_items WHERE refresh_run_id=? ORDER BY subject_type, subject_key, id", (run_id,)).fetchall()]
    result["changes"] = list_changes(connection, run_id=run_id)
    return result
