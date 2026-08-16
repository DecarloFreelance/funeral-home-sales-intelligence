from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import dataclass
from enum import StrEnum

from canada_funeral_intel.people.models import PersonResolutionError
from canada_funeral_intel.storage.database import transaction


class RemediationStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    STALE = "stale"


TASK_TYPES = (
    "verify_contact",
    "verify_affiliation",
    "verify_identity",
    "inspect_source",
    "inspect_page",
    "confirm_branch",
    "resolve_conflict",
    "other",
)
ACTIVE_STATUSES = frozenset(
    {RemediationStatus.OPEN, RemediationStatus.IN_PROGRESS, RemediationStatus.BLOCKED}
)
_TRANSITIONS: dict[RemediationStatus, frozenset[RemediationStatus]] = {
    RemediationStatus.OPEN: frozenset(
        {
            RemediationStatus.IN_PROGRESS,
            RemediationStatus.BLOCKED,
            RemediationStatus.COMPLETED,
            RemediationStatus.CANCELLED,
        }
    ),
    RemediationStatus.IN_PROGRESS: frozenset(
        {
            RemediationStatus.BLOCKED,
            RemediationStatus.COMPLETED,
            RemediationStatus.CANCELLED,
        }
    ),
    RemediationStatus.BLOCKED: frozenset(
        {
            RemediationStatus.IN_PROGRESS,
            RemediationStatus.COMPLETED,
            RemediationStatus.CANCELLED,
        }
    ),
    RemediationStatus.COMPLETED: frozenset({RemediationStatus.OPEN}),
    RemediationStatus.CANCELLED: frozenset({RemediationStatus.OPEN}),
    RemediationStatus.STALE: frozenset(),
}


@dataclass(frozen=True, slots=True)
class RemediationResult:
    task_id: int
    person_id: int
    anomaly_code: str
    anomaly_fingerprint: str
    status: RemediationStatus
    actor: str
    changed: bool


def _validate_actor(actor: str) -> str:
    actor = actor.strip()
    if not actor:
        raise PersonResolutionError("actor is required")
    return actor


def _validate_due_at(due_at: str | None) -> str | None:
    if due_at is None or not due_at.strip():
        return None
    value = due_at.strip()
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError as exc:
        raise PersonResolutionError(
            "due_at must be a valid ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise PersonResolutionError("due_at must include a timezone")
    return value


def _current_anomaly(
    connection: sqlite3.Connection, person_id: int, anomaly_code: str, fingerprint: str
) -> None:
    from canada_funeral_intel.people.dispositions import _find_current_anomaly

    _find_current_anomaly(connection, person_id, anomaly_code, fingerprint)


def _history(
    connection: sqlite3.Connection,
    *,
    task: sqlite3.Row,
    previous_status: str | None,
    new_status: str,
    actor: str,
    note: str | None,
    previous_owner: str | None,
    new_owner: str | None,
    previous_due_at: str | None,
    new_due_at: str | None,
) -> None:
    connection.execute(
        """INSERT INTO person_anomaly_remediation_task_history
        (task_id, person_id, anomaly_code, anomaly_fingerprint, previous_status, new_status,
         actor, note, previous_owner, new_owner, previous_due_at, new_due_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            task["id"],
            task["person_id"],
            task["anomaly_code"],
            task["anomaly_fingerprint"],
            previous_status,
            new_status,
            actor,
            note,
            previous_owner,
            new_owner,
            previous_due_at,
            new_due_at,
        ),
    )


def create_task(
    connection: sqlite3.Connection,
    *,
    person_id: int,
    anomaly_code: str,
    fingerprint: str,
    task_type: str,
    actor: str,
    owner: str | None = None,
    due_at: str | None = None,
    note: str | None = None,
) -> RemediationResult:
    actor = _validate_actor(actor)
    if task_type not in TASK_TYPES:
        raise PersonResolutionError("invalid remediation task type")
    owner = owner.strip() if owner and owner.strip() else None
    due_at = _validate_due_at(due_at)
    note = note.strip() if note else None
    try:
        with transaction(connection):
            _current_anomaly(connection, person_id, anomaly_code, fingerprint)
            cursor = connection.execute(
                """INSERT INTO person_anomaly_remediation_tasks
                (person_id, anomaly_code, anomaly_fingerprint, task_type, status, owner, due_at, created_by, created_note)
                VALUES (?, ?, ?, ?, 'open', ?, ?, ?, ?)""",
                (
                    person_id,
                    anomaly_code,
                    fingerprint,
                    task_type,
                    owner,
                    due_at,
                    actor,
                    note,
                ),
            )
            task_id = int(cursor.lastrowid)
            row = connection.execute(
                "SELECT * FROM person_anomaly_remediation_tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
            _history(
                connection,
                task=row,
                previous_status=None,
                new_status="open",
                actor=actor,
                note=note,
                previous_owner=None,
                new_owner=owner,
                previous_due_at=None,
                new_due_at=due_at,
            )
            return RemediationResult(
                task_id,
                person_id,
                anomaly_code,
                fingerprint,
                RemediationStatus.OPEN,
                actor,
                True,
            )
    except sqlite3.IntegrityError as exc:
        raise PersonResolutionError(
            f"remediation task violated a database constraint: {exc}"
        ) from exc
    except sqlite3.Error as exc:
        raise PersonResolutionError(f"remediation task creation failed: {exc}") from exc


def update_task(
    connection: sqlite3.Connection,
    *,
    task_id: int,
    actor: str,
    status: RemediationStatus | None = None,
    owner: str | None = None,
    due_at: str | None = None,
    note: str | None = None,
    clear_owner: bool = False,
    clear_due_at: bool = False,
) -> RemediationResult:
    actor = _validate_actor(actor)
    if task_id < 1:
        raise PersonResolutionError("task_id must be positive")
    due_at = _validate_due_at(due_at) if due_at is not None else None
    if status is RemediationStatus.STALE:
        raise PersonResolutionError("stale is assigned only by remediation-sync")
    try:
        with transaction(connection):
            row = connection.execute(
                "SELECT * FROM person_anomaly_remediation_tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
            if row is None:
                raise PersonResolutionError(f"Remediation task not found: {task_id}")
            current = RemediationStatus(str(row["status"]))
            new_status = status or current
            if (
                status is not None
                and status is not current
                and status not in _TRANSITIONS[current]
            ):
                raise PersonResolutionError(
                    f"invalid remediation transition: {current.value} -> {status.value}"
                )
            new_owner = (
                None
                if clear_owner
                else (
                    owner.strip()
                    if owner is not None and owner.strip()
                    else (row["owner"] if owner is None else None)
                )
            )
            new_due = (
                None
                if clear_due_at
                else (due_at if due_at is not None else row["due_at"])
            )
            new_note = (
                note.strip()
                if note is not None and note.strip()
                else row["created_note"]
            )
            changed = (
                new_status.value != row["status"]
                or new_owner != row["owner"]
                or new_due != row["due_at"]
                or new_note != row["created_note"]
            )
            if not changed:
                return RemediationResult(
                    task_id,
                    int(row["person_id"]),
                    str(row["anomaly_code"]),
                    str(row["anomaly_fingerprint"]),
                    current,
                    actor,
                    False,
                )
            connection.execute(
                """UPDATE person_anomaly_remediation_tasks SET status = ?, owner = ?, due_at = ?, created_note = ?,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                completed_at = CASE WHEN ? = 'completed' THEN strftime('%Y-%m-%dT%H:%M:%fZ', 'now') ELSE completed_at END,
                cancelled_at = CASE WHEN ? = 'cancelled' THEN strftime('%Y-%m-%dT%H:%M:%fZ', 'now') ELSE cancelled_at END
                WHERE id = ? AND status = ?""",
                (
                    new_status.value,
                    new_owner,
                    new_due,
                    new_note,
                    new_status.value,
                    new_status.value,
                    task_id,
                    current.value,
                ),
            )
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise PersonResolutionError(
                    "remediation task changed concurrently; retry"
                )
            _history(
                connection,
                task=row,
                previous_status=current.value,
                new_status=new_status.value,
                actor=actor,
                note=note,
                previous_owner=row["owner"],
                new_owner=new_owner,
                previous_due_at=row["due_at"],
                new_due_at=new_due,
            )
            return RemediationResult(
                task_id,
                int(row["person_id"]),
                str(row["anomaly_code"]),
                str(row["anomaly_fingerprint"]),
                new_status,
                actor,
                True,
            )
    except sqlite3.Error as exc:
        raise PersonResolutionError(f"remediation task update failed: {exc}") from exc


def _current_fingerprints(
    connection: sqlite3.Connection, person_id: int
) -> set[tuple[str, str]]:
    from canada_funeral_intel.people.dispositions import _current_anomalies

    return {
        (str(item["code"]), str(item["fingerprint"]))
        for item in _current_anomalies(connection, person_id)
    }


def sync_tasks(
    connection: sqlite3.Connection,
    *,
    person_id: int | None = None,
    actor: str = "remediation-sync",
) -> dict[str, int]:
    actor = _validate_actor(actor)
    query = "SELECT * FROM person_anomaly_remediation_tasks"
    parameters: tuple[object, ...] = ()
    if person_id is not None:
        if person_id < 1:
            raise PersonResolutionError("person_id must be positive")
        query += " WHERE person_id = ?"
        parameters = (person_id,)
    try:
        with transaction(connection):
            rows = connection.execute(query + " ORDER BY id", parameters).fetchall()
            cache: dict[int, set[tuple[str, str]]] = {}
            marked = 0
            for row in rows:
                pid = int(row["person_id"])
                cache.setdefault(pid, _current_fingerprints(connection, pid))
                if (
                    row["status"] != RemediationStatus.STALE.value
                    and (str(row["anomaly_code"]), str(row["anomaly_fingerprint"]))
                    not in cache[pid]
                ):
                    connection.execute(
                        "UPDATE person_anomaly_remediation_tasks SET status = 'stale', stale_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ? AND status = ?",
                        (row["id"], row["status"]),
                    )
                    if connection.execute("SELECT changes()").fetchone()[0] == 1:
                        _history(
                            connection,
                            task=row,
                            previous_status=str(row["status"]),
                            new_status="stale",
                            actor=actor,
                            note="fingerprint no longer present in current triage",
                            previous_owner=row["owner"],
                            new_owner=row["owner"],
                            previous_due_at=row["due_at"],
                            new_due_at=row["due_at"],
                        )
                        marked += 1
            return {"checked": len(rows), "marked_stale": marked}
    except sqlite3.Error as exc:
        raise PersonResolutionError(f"remediation sync failed: {exc}") from exc


def list_tasks(
    connection: sqlite3.Connection,
    *,
    person_id: int | None = None,
    anomaly_code: str | None = None,
    fingerprint: str | None = None,
    status: RemediationStatus | None = None,
    owner: str | None = None,
    task_type: str | None = None,
    due_before: str | None = None,
    due_after: str | None = None,
    include_stale: bool = False,
    overdue_only: bool = False,
    now: str | None = None,
    limit: int | None = None,
) -> list[dict[str, object]]:
    if limit is not None and limit < 1:
        raise PersonResolutionError("limit must be positive")
    conditions: list[str] = []
    parameters: list[object] = []
    if person_id is not None:
        conditions += ["t.person_id = ?"]
        parameters.append(person_id)
    if anomaly_code is not None:
        conditions += ["t.anomaly_code = ?"]
        parameters.append(anomaly_code)
    if fingerprint is not None:
        conditions += ["t.anomaly_fingerprint = ?"]
        parameters.append(fingerprint)
    if status is not None:
        conditions += ["t.status = ?"]
        parameters.append(status.value)
    if owner is not None:
        conditions += ["t.owner = ?"]
        parameters.append(owner.strip())
    if task_type is not None:
        if task_type not in TASK_TYPES:
            raise PersonResolutionError("invalid remediation task type")
        conditions += ["t.task_type = ?"]
        parameters.append(task_type)
    if not include_stale:
        conditions.append("t.status <> 'stale'")
    if due_before is not None:
        _validate_due_at(due_before)
        conditions.append("t.due_at < ?")
        parameters.append(due_before)
    if due_after is not None:
        _validate_due_at(due_after)
        conditions.append("t.due_at > ?")
        parameters.append(due_after)
    if overdue_only:
        reference = (
            _validate_due_at(now)
            if now is not None
            else dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")
        )
        conditions.append(
            "t.due_at IS NOT NULL AND t.due_at < ? AND t.status IN ('open', 'in_progress', 'blocked')"
        )
        parameters.append(reference)
    query = "SELECT t.* FROM person_anomaly_remediation_tasks AS t"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY CASE WHEN t.status = 'stale' THEN 1 ELSE 0 END, CASE WHEN t.status IN ('open', 'in_progress', 'blocked') AND t.due_at IS NOT NULL AND t.due_at < COALESCE(?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) THEN 0 ELSE 1 END, CASE WHEN t.due_at IS NULL THEN 1 ELSE 0 END, t.due_at, t.person_id, t.id"
    parameters.append(now)
    if limit is not None:
        query += " LIMIT ?"
        parameters.append(limit)
    try:
        return [
            dict(row) for row in connection.execute(query, tuple(parameters)).fetchall()
        ]
    except sqlite3.Error as exc:
        raise PersonResolutionError(f"remediation task listing failed: {exc}") from exc


def show_task(connection: sqlite3.Connection, task_id: int) -> dict[str, object]:
    if task_id < 1:
        raise PersonResolutionError("task_id must be positive")
    row = connection.execute(
        "SELECT * FROM person_anomaly_remediation_tasks WHERE id = ?", (task_id,)
    ).fetchone()
    if row is None:
        raise PersonResolutionError(f"Remediation task not found: {task_id}")
    current = any(
        code == row["anomaly_code"] and fingerprint == row["anomaly_fingerprint"]
        for code, fingerprint in _current_fingerprints(
            connection, int(row["person_id"])
        )
    )
    history = connection.execute(
        "SELECT * FROM person_anomaly_remediation_task_history WHERE task_id = ? ORDER BY id",
        (task_id,),
    ).fetchall()
    return {
        "task": dict(row),
        "current_anomaly": current,
        "history": [dict(item) for item in history],
    }


def task_history(
    connection: sqlite3.Connection, task_id: int
) -> list[dict[str, object]]:
    if task_id < 1:
        raise PersonResolutionError("task_id must be positive")
    return [
        dict(row)
        for row in connection.execute(
            "SELECT * FROM person_anomaly_remediation_task_history WHERE task_id = ? ORDER BY id",
            (task_id,),
        ).fetchall()
    ]


def summaries_for_fingerprints(
    connection: sqlite3.Connection,
    keys: list[tuple[int, str, str]],
    *,
    now: str | None = None,
) -> dict[tuple[int, str, str], dict[str, object]]:
    if not keys:
        return {}
    clauses = " OR ".join(
        "(person_id = ? AND anomaly_code = ? AND anomaly_fingerprint = ?)" for _ in keys
    )
    parameters = tuple(value for key in keys for value in key)
    rows = connection.execute(
        f"SELECT * FROM person_anomaly_remediation_tasks WHERE {clauses} ORDER BY id",
        parameters,
    ).fetchall()
    reference = now or dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")
    result: dict[tuple[int, str, str], dict[str, object]] = {}
    for key in keys:
        matches = [
            row
            for row in rows
            if (
                int(row["person_id"]),
                str(row["anomaly_code"]),
                str(row["anomaly_fingerprint"]),
            )
            == key
        ]
        active = [
            row
            for row in matches
            if row["status"] in {item.value for item in ACTIVE_STATUSES}
        ]
        overdue = [
            row for row in active if row["due_at"] and str(row["due_at"]) < reference
        ]
        active_due = [str(row["due_at"]) for row in active if row["due_at"]]
        result[key] = {
            "remediation_task_count": len(matches),
            "active_remediation_task_count": len(active),
            "open_remediation_task_count": sum(
                row["status"] == RemediationStatus.OPEN.value for row in matches
            ),
            "in_progress_remediation_task_count": sum(
                row["status"] == RemediationStatus.IN_PROGRESS.value for row in matches
            ),
            "blocked_remediation_task_count": sum(
                row["status"] == RemediationStatus.BLOCKED.value for row in matches
            ),
            "overdue_remediation_task_count": len(overdue),
            "stale_remediation_task_count": sum(
                row["status"] == RemediationStatus.STALE.value for row in matches
            ),
            "completed_remediation_task_count": sum(
                row["status"] == RemediationStatus.COMPLETED.value for row in matches
            ),
            "cancelled_remediation_task_count": sum(
                row["status"] == RemediationStatus.CANCELLED.value for row in matches
            ),
            "remediation_statuses": sorted({str(row["status"]) for row in matches}),
            "remediation_task_ids": sorted(int(row["id"]) for row in matches),
            "remediation_owners": sorted(
                {str(row["owner"]) for row in matches if row["owner"]}
            ),
            "next_due_at": min(active_due) if active_due else None,
        }
    return result
