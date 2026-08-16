from __future__ import annotations

import csv
import datetime as dt
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from canada_funeral_intel.people.models import PersonResolutionError
from canada_funeral_intel.people.triage import (
    TriageFilters,
    triage_people,
)

SEVERITY_BASE = {"critical": 400, "high": 300, "medium": 200, "low": 100}
SEVERITY_RANK = {"critical": 1, "high": 2, "medium": 3, "low": 4}
ACTIVE_TASK_STATUSES = {"open", "in_progress", "blocked"}


@dataclass(frozen=True, slots=True)
class WorkQueueFilters:
    person_id: int | None = None
    entity_id: int | None = None
    anomaly: str | None = None
    severity: str | None = None
    traceability: str | None = None
    disposition_status: str | None = None
    queue_state: str | None = None
    owner: str | None = None
    unassigned_only: bool = False
    has_remediation: bool = False
    no_remediation: bool = False
    overdue_only: bool = False
    blocked_only: bool = False
    stale_only: bool = False
    include_stale: bool = False
    include_historical: bool = False
    due_before: str | None = None
    due_after: str | None = None
    limit: int | None = None
    reference_time: dt.datetime | None = None


def _reference(value: dt.datetime | None) -> str:
    value = value or dt.datetime.now(dt.UTC)
    if value.tzinfo is None:
        raise PersonResolutionError("reference_time must include a timezone")
    return value.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def _validate(filters: WorkQueueFilters) -> None:
    if filters.person_id is not None and filters.person_id < 1:
        raise PersonResolutionError("person_id must be positive")
    if filters.entity_id is not None and filters.entity_id < 1:
        raise PersonResolutionError("entity_id must be positive")
    if filters.limit is not None and filters.limit < 1:
        raise PersonResolutionError("limit must be positive")
    if filters.has_remediation and filters.no_remediation:
        raise PersonResolutionError(
            "has_remediation and no_remediation cannot be combined"
        )


def _workflow_state(
    anomaly: dict[str, object], *, stale_work: bool, reference: str
) -> tuple[str, list[str], int]:
    disposition = anomaly.get("disposition")
    remediation = anomaly.get("remediation") or {}
    reasons: list[str] = []
    priority = SEVERITY_BASE[str(anomaly["severity"])]
    if remediation.get("overdue_remediation_task_count", 0):
        reasons.append("overdue_remediation")
        priority += 80
        state = "remediation_overdue"
    elif remediation.get("blocked_remediation_task_count", 0):
        reasons.append("blocked_remediation")
        priority += 60
        state = "remediation_blocked"
    elif remediation.get("in_progress_remediation_task_count", 0):
        reasons.append("in_progress_remediation")
        priority += 40
        state = "remediation_in_progress"
    elif remediation.get("open_remediation_task_count", 0):
        reasons.append("open_remediation")
        priority += 20
        state = "remediation_open"
    elif disposition is None:
        reasons.append("unreviewed")
        priority += 40
        state = "unreviewed"
    elif disposition["status"] == "acknowledged":
        state = "acknowledged"
    elif disposition["status"] == "dismissed":
        state = "dismissed"
    else:
        state = str(disposition["status"])
    if remediation.get("next_due_at"):
        due = dt.datetime.fromisoformat(str(remediation["next_due_at"]))
        ref = dt.datetime.fromisoformat(reference)
        if due <= ref + dt.timedelta(hours=72):
            reasons.append("due_within_72_hours")
            priority += 10
    if state == "acknowledged" and not remediation.get("active_remediation_task_count"):
        reasons.append("acknowledged_no_active_remediation")
        priority -= 20
    if state == "dismissed" and not remediation.get("active_remediation_task_count"):
        reasons.append("dismissed_no_active_remediation")
        priority -= 40
    if (
        stale_work
        and not remediation.get("remediation_task_count")
        and disposition is None
    ):
        state = "stale_work"
        reasons.append("stale_work")
    return state, reasons, priority


def _stale_context(
    connection: sqlite3.Connection, person_ids: list[int]
) -> set[tuple[int, str]]:
    if not person_ids:
        return set()
    marks = ",".join("?" for _ in person_ids)
    rows = connection.execute(
        f"SELECT person_id, anomaly_code FROM person_anomaly_dispositions WHERE person_id IN ({marks}) AND status = 'stale' UNION SELECT person_id, anomaly_code FROM person_anomaly_remediation_tasks WHERE person_id IN ({marks}) AND status = 'stale'",
        tuple(person_ids) + tuple(person_ids),
    ).fetchall()
    return {(int(row["person_id"]), str(row["anomaly_code"])) for row in rows}


def _rows(
    connection: sqlite3.Connection, filters: WorkQueueFilters
) -> list[dict[str, object]]:
    reference = _reference(filters.reference_time)
    triage_filters = TriageFilters(
        person_id=filters.person_id,
        traceability=filters.traceability,
        entity_id=filters.entity_id,
        include_historical=filters.include_historical,
        reference_time=reference,
    )
    people = triage_people(connection, triage_filters)
    stale = (
        _stale_context(connection, [int(row["person_id"]) for row in people])
        if filters.include_stale or filters.stale_only
        else set()
    )
    output: list[dict[str, object]] = []
    for person in people:
        for anomaly in person["anomalies"]:
            remediation = anomaly.get("remediation") or {}
            if filters.anomaly is not None and anomaly["code"] != filters.anomaly:
                continue
            if filters.severity is not None and anomaly["severity"] != filters.severity:
                continue
            if filters.disposition_status is not None and (
                not anomaly.get("disposition")
                or anomaly["disposition"]["status"] != filters.disposition_status
            ):
                continue
            if filters.has_remediation and not remediation.get(
                "remediation_task_count"
            ):
                continue
            if filters.no_remediation and remediation.get("remediation_task_count"):
                continue
            if filters.overdue_only and not remediation.get(
                "overdue_remediation_task_count"
            ):
                continue
            if filters.owner is not None and filters.owner not in remediation.get(
                "remediation_owners", []
            ):
                continue
            if filters.unassigned_only and remediation.get("remediation_owners"):
                continue
            if filters.blocked_only and not remediation.get(
                "blocked_remediation_task_count"
            ):
                continue
            if filters.due_before and (
                not remediation.get("next_due_at")
                or remediation["next_due_at"] >= filters.due_before
            ):
                continue
            if filters.due_after and (
                not remediation.get("next_due_at")
                or remediation["next_due_at"] <= filters.due_after
            ):
                continue
            has_stale = (int(person["person_id"]), str(anomaly["code"])) in stale
            if filters.stale_only and not has_stale:
                continue
            state, reasons, priority = _workflow_state(
                anomaly, stale_work=has_stale, reference=reference
            )
            if filters.queue_state and state != filters.queue_state:
                continue
            output.append(
                {
                    "person_id": person["person_id"],
                    "canonical_name": person["display_name"],
                    "person_status": person["person_status"],
                    "entity_id": (anomaly["supporting_ids"]["entity_ids"] or [None])[0],
                    "anomaly_code": anomaly["code"],
                    "anomaly_fingerprint": anomaly["fingerprint"],
                    "severity": anomaly["severity"],
                    "traceability_status": person["traceability_status"],
                    "disposition_status": (anomaly.get("disposition") or {}).get(
                        "status"
                    ),
                    "queue_state": state,
                    "computed_priority": priority,
                    "priority_reasons": reasons,
                    "supporting_ids": anomaly["supporting_ids"],
                    **{
                        key: remediation.get(key, 0)
                        for key in (
                            "remediation_task_count",
                            "active_remediation_task_count",
                            "open_remediation_task_count",
                            "in_progress_remediation_task_count",
                            "blocked_remediation_task_count",
                            "overdue_remediation_task_count",
                            "stale_remediation_task_count",
                            "completed_remediation_task_count",
                        )
                    },
                    "remediation_owners": remediation.get("remediation_owners", []),
                    "next_due_at": remediation.get("next_due_at"),
                    "has_current_remediation": bool(
                        remediation.get("active_remediation_task_count")
                    ),
                    "has_stale_work": has_stale,
                }
            )
    output.sort(
        key=lambda row: (
            -int(row["computed_priority"]),
            SEVERITY_RANK[str(row["severity"])],
            -int(bool(row["overdue_remediation_task_count"])),
            -int(bool(row["blocked_remediation_task_count"])),
            row["next_due_at"] is None,
            row["next_due_at"] or "",
            int(row["person_id"]),
            str(row["anomaly_code"]),
            str(row["anomaly_fingerprint"]),
        )
    )
    return output[: filters.limit] if filters.limit is not None else output


def list_work_queue(
    connection: sqlite3.Connection, filters: WorkQueueFilters | None = None
) -> list[dict[str, object]]:
    filters = filters or WorkQueueFilters()
    _validate(filters)
    return _rows(connection, filters)


def show_work_item(
    connection: sqlite3.Connection,
    *,
    person_id: int,
    fingerprint: str,
    include_historical: bool = False,
    reference_time: dt.datetime | None = None,
) -> dict[str, object]:
    rows = list_work_queue(
        connection,
        WorkQueueFilters(
            person_id=person_id,
            include_historical=include_historical,
            reference_time=reference_time,
        ),
    )
    matches = [row for row in rows if row["anomaly_fingerprint"] == fingerprint]
    if not matches:
        raise PersonResolutionError("current anomaly fingerprint not found")
    return matches[0]


def owner_workload(
    connection: sqlite3.Connection,
    *,
    include_historical: bool = False,
    reference_time: dt.datetime | None = None,
) -> list[dict[str, object]]:
    rows = list_work_queue(
        connection,
        WorkQueueFilters(
            include_historical=include_historical, reference_time=reference_time
        ),
    )
    owners: dict[str | None, list[dict[str, object]]] = {}
    row_by_key = {
        (
            int(row["person_id"]),
            str(row["anomaly_code"]),
            str(row["anomaly_fingerprint"]),
        ): row
        for row in rows
    }
    if row_by_key:
        person_ids = sorted({key[0] for key in row_by_key})
        marks = ",".join("?" for _ in person_ids)
        tasks = connection.execute(
            f"SELECT * FROM person_anomaly_remediation_tasks WHERE person_id IN ({marks}) ORDER BY id",
            tuple(person_ids),
        ).fetchall()
        for task in tasks:
            if task["status"] == "stale":
                continue
            key = (
                int(task["person_id"]),
                str(task["anomaly_code"]),
                str(task["anomaly_fingerprint"]),
            )
            row = row_by_key.get(key)
            if row is None:
                continue
            owner = None if task["owner"] is None else str(task["owner"])
            owners.setdefault(owner, []).append({"row": row, "task": task})
    for row in rows:
        if not row["remediation_task_count"]:
            owners.setdefault(None, []).append({"row": row, "task": None})
    output = []
    for owner, items in owners.items():
        queue_rows = [item["row"] for item in items]
        tasks = [item["task"] for item in items if item["task"] is not None]
        people = {int(row["person_id"]) for row in queue_rows}
        output.append(
            {
                "owner": owner,
                "people_count": len(people),
                "anomaly_count": len(
                    {
                        (int(row["person_id"]), str(row["anomaly_fingerprint"]))
                        for row in queue_rows
                    }
                ),
                "active_task_count": sum(
                    task["status"] in ACTIVE_TASK_STATUSES for task in tasks
                ),
                "open_task_count": sum(task["status"] == "open" for task in tasks),
                "in_progress_task_count": sum(
                    task["status"] == "in_progress" for task in tasks
                ),
                "blocked_task_count": sum(
                    task["status"] == "blocked" for task in tasks
                ),
                "overdue_task_count": sum(
                    task["status"] in ACTIVE_TASK_STATUSES
                    and task["due_at"] is not None
                    and str(task["due_at"]) < _reference(reference_time)
                    for task in tasks
                ),
                **{
                    f"{level}_anomaly_count": len(
                        {
                            (int(row["person_id"]), str(row["anomaly_fingerprint"]))
                            for row in queue_rows
                            if row["severity"] == level
                        }
                    )
                    for level in ("critical", "high", "medium", "low")
                },
                "next_due_at": min(
                    (
                        str(task["due_at"])
                        for task in tasks
                        if task["due_at"] is not None
                        and task["status"] in ACTIVE_TASK_STATUSES
                    ),
                    default=None,
                ),
            }
        )
    output.sort(key=lambda row: (row["owner"] is not None, row["owner"] or ""))
    return output


QUEUE_COLUMNS = (
    "person_id",
    "canonical_name",
    "person_status",
    "entity_id",
    "anomaly_code",
    "anomaly_fingerprint",
    "severity",
    "traceability_status",
    "disposition_status",
    "queue_state",
    "computed_priority",
    "priority_reasons",
    "remediation_task_count",
    "active_remediation_task_count",
    "open_remediation_task_count",
    "in_progress_remediation_task_count",
    "blocked_remediation_task_count",
    "overdue_remediation_task_count",
    "stale_remediation_task_count",
    "completed_remediation_task_count",
    "remediation_owners",
    "next_due_at",
    "has_stale_work",
    "supporting_ids",
)
OWNER_COLUMNS = (
    "owner",
    "people_count",
    "anomaly_count",
    "active_task_count",
    "open_task_count",
    "in_progress_task_count",
    "blocked_task_count",
    "overdue_task_count",
    "critical_anomaly_count",
    "high_anomaly_count",
    "medium_anomaly_count",
    "low_anomaly_count",
    "next_due_at",
)


def _cell(value: object) -> object:
    if isinstance(value, list):
        return "|".join(str(item) for item in value)
    if isinstance(value, dict):
        return "|".join(f"{key}:{_cell(value[key])}" for key in sorted(value))
    return value


def export_work_queue_csv(
    connection: sqlite3.Connection,
    output: Path,
    *,
    include_historical: bool = False,
    reference_time: dt.datetime | None = None,
) -> list[Path]:
    if output.exists() and not output.is_dir():
        raise PersonResolutionError("work queue output must be a directory")
    output.mkdir(parents=True, exist_ok=True)
    rows = list_work_queue(
        connection,
        WorkQueueFilters(
            include_historical=include_historical, reference_time=reference_time
        ),
    )
    owners = owner_workload(
        connection, include_historical=include_historical, reference_time=reference_time
    )
    path = output / "person_work_queue.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=QUEUE_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {column: _cell(row.get(column)) for column in QUEUE_COLUMNS}
            )
    owner_path = output / "person_work_queue_owners.csv"
    with owner_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OWNER_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in owners:
            writer.writerow(
                {column: _cell(row.get(column)) for column in OWNER_COLUMNS}
            )
    return [path, owner_path]
