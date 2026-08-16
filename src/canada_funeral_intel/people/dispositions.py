from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from enum import StrEnum

from canada_funeral_intel.people.models import PersonResolutionError
from canada_funeral_intel.storage.database import transaction


class DispositionStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    DISMISSED = "dismissed"
    REOPENED = "reopened"
    STALE = "stale"


_ALLOWED_TRANSITIONS: dict[DispositionStatus, frozenset[DispositionStatus]] = {
    DispositionStatus.OPEN: frozenset(
        {DispositionStatus.ACKNOWLEDGED, DispositionStatus.DISMISSED}
    ),
    DispositionStatus.ACKNOWLEDGED: frozenset({DispositionStatus.REOPENED}),
    DispositionStatus.DISMISSED: frozenset({DispositionStatus.REOPENED}),
    DispositionStatus.REOPENED: frozenset(
        {DispositionStatus.ACKNOWLEDGED, DispositionStatus.DISMISSED}
    ),
    DispositionStatus.STALE: frozenset({DispositionStatus.REOPENED}),
}


@dataclass(frozen=True, slots=True)
class DispositionResult:
    disposition_id: int
    person_id: int
    anomaly_code: str
    anomaly_fingerprint: str
    status: DispositionStatus
    actor: str
    note: str | None
    changed_at: str
    changed: bool


def fingerprint_anomaly(person_id: int, anomaly: dict[str, object]) -> str:
    if person_id < 1:
        raise PersonResolutionError("person_id must be positive")
    supporting = anomaly.get("supporting_ids") or {}
    payload = {
        "version": 1,
        "person_id": person_id,
        "anomaly_code": str(anomaly.get("code", "")),
        "supporting": {
            key: sorted({int(value) for value in supporting.get(key, [])})
            for key in (
                "person_ids",
                "observation_ids",
                "affiliation_ids",
                "contact_ids",
                "merge_ids",
                "entity_ids",
                "website_ids",
                "page_ids",
            )
        },
    }
    if not payload["anomaly_code"]:
        raise PersonResolutionError("anomaly code is required")
    if anomaly.get("values"):
        payload["values"] = sorted({str(value) for value in anomaly["values"]})
    serialized = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _current_anomalies(
    connection: sqlite3.Connection, person_id: int
) -> list[dict[str, object]]:
    from canada_funeral_intel.people.triage import TriageFilters, triage_people

    records = triage_people(
        connection, TriageFilters(person_id=person_id, include_historical=True)
    )
    if not records:
        raise PersonResolutionError(f"Person not found: {person_id}")
    return [
        {**anomaly, "fingerprint": fingerprint_anomaly(person_id, anomaly)}
        for anomaly in records[0]["anomalies"]
    ]


def _find_current_anomaly(
    connection: sqlite3.Connection, person_id: int, anomaly_code: str, fingerprint: str
) -> dict[str, object]:
    for anomaly in _current_anomalies(connection, person_id):
        if anomaly["code"] == anomaly_code and anomaly["fingerprint"] == fingerprint:
            return anomaly
    raise PersonResolutionError(
        "anomaly code and fingerprint do not match current triage state"
    )


def _timestamp(connection: sqlite3.Connection, disposition_id: int) -> str:
    row = connection.execute(
        "SELECT updated_at FROM person_anomaly_dispositions WHERE id = ?",
        (disposition_id,),
    ).fetchone()
    if row is None:
        raise PersonResolutionError("disposition update could not be read")
    return str(row["updated_at"])


def decide_disposition(
    connection: sqlite3.Connection,
    *,
    person_id: int,
    anomaly_code: str,
    fingerprint: str,
    status: DispositionStatus,
    actor: str,
    note: str | None = None,
) -> DispositionResult:
    if not actor.strip():
        raise PersonResolutionError("actor is required")
    if status in {DispositionStatus.OPEN, DispositionStatus.STALE}:
        raise PersonResolutionError("open and stale are not reviewer decision statuses")
    actor = actor.strip()
    note = note.strip() if note else None
    try:
        with transaction(connection):
            _find_current_anomaly(connection, person_id, anomaly_code, fingerprint)
            row = connection.execute(
                "SELECT * FROM person_anomaly_dispositions WHERE person_id = ? AND anomaly_code = ? AND anomaly_fingerprint = ?",
                (person_id, anomaly_code, fingerprint),
            ).fetchone()
            if row is None:
                if status not in {
                    DispositionStatus.ACKNOWLEDGED,
                    DispositionStatus.DISMISSED,
                }:
                    raise PersonResolutionError(
                        "a new disposition must be acknowledged or dismissed"
                    )
                cursor = connection.execute(
                    """
                    INSERT INTO person_anomaly_dispositions
                    (person_id, anomaly_code, anomaly_fingerprint, status, reviewer_actor,
                     reviewer_note, acknowledged_at, dismissed_at)
                    VALUES (?, ?, ?, ?, ?, ?,
                            CASE WHEN ? = 'acknowledged' THEN strftime('%Y-%m-%dT%H:%M:%fZ', 'now') END,
                            CASE WHEN ? = 'dismissed' THEN strftime('%Y-%m-%dT%H:%M:%fZ', 'now') END)
                    """,
                    (
                        person_id,
                        anomaly_code,
                        fingerprint,
                        status.value,
                        actor,
                        note,
                        status.value,
                        status.value,
                    ),
                )
                disposition_id = int(cursor.lastrowid)
                connection.execute(
                    "INSERT INTO person_anomaly_disposition_history (disposition_id, person_id, anomaly_code, anomaly_fingerprint, previous_status, new_status, actor, note) VALUES (?, ?, ?, ?, NULL, ?, ?, ?)",
                    (
                        disposition_id,
                        person_id,
                        anomaly_code,
                        fingerprint,
                        status.value,
                        actor,
                        note,
                    ),
                )
                return DispositionResult(
                    disposition_id,
                    person_id,
                    anomaly_code,
                    fingerprint,
                    status,
                    actor,
                    note,
                    _timestamp(connection, disposition_id),
                    True,
                )

            current = DispositionStatus(str(row["status"]))
            if current is status:
                return DispositionResult(
                    int(row["id"]),
                    person_id,
                    anomaly_code,
                    fingerprint,
                    current,
                    str(row["reviewer_actor"]),
                    None if row["reviewer_note"] is None else str(row["reviewer_note"]),
                    str(row["updated_at"]),
                    False,
                )
            if status not in _ALLOWED_TRANSITIONS[current]:
                raise PersonResolutionError(
                    f"invalid disposition transition: {current.value} -> {status.value}"
                )
            connection.execute(
                """
                UPDATE person_anomaly_dispositions
                SET status = ?, reviewer_actor = ?, reviewer_note = ?,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                    acknowledged_at = CASE WHEN ? = 'acknowledged' THEN strftime('%Y-%m-%dT%H:%M:%fZ', 'now') ELSE acknowledged_at END,
                    dismissed_at = CASE WHEN ? = 'dismissed' THEN strftime('%Y-%m-%dT%H:%M:%fZ', 'now') ELSE dismissed_at END,
                    reopened_at = CASE WHEN ? = 'reopened' THEN strftime('%Y-%m-%dT%H:%M:%fZ', 'now') ELSE reopened_at END
                WHERE id = ? AND status = ?
                """,
                (
                    status.value,
                    actor,
                    note,
                    status.value,
                    status.value,
                    status.value,
                    int(row["id"]),
                    current.value,
                ),
            )
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise PersonResolutionError("disposition changed concurrently; retry")
            connection.execute(
                "INSERT INTO person_anomaly_disposition_history (disposition_id, person_id, anomaly_code, anomaly_fingerprint, previous_status, new_status, actor, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    int(row["id"]),
                    person_id,
                    anomaly_code,
                    fingerprint,
                    current.value,
                    status.value,
                    actor,
                    note,
                ),
            )
            return DispositionResult(
                int(row["id"]),
                person_id,
                anomaly_code,
                fingerprint,
                status,
                actor,
                note,
                _timestamp(connection, int(row["id"])),
                True,
            )
    except sqlite3.IntegrityError as exc:
        raise PersonResolutionError(
            f"disposition update violated a database constraint: {exc}"
        ) from exc
    except sqlite3.Error as exc:
        raise PersonResolutionError(f"disposition update failed: {exc}") from exc


def sync_dispositions(
    connection: sqlite3.Connection,
    *,
    person_id: int | None = None,
    actor: str = "anomaly-sync",
) -> dict[str, int]:
    if not actor.strip():
        raise PersonResolutionError("actor is required")
    try:
        with transaction(connection):
            query = "SELECT id, person_id, anomaly_code, anomaly_fingerprint, status FROM person_anomaly_dispositions"
            parameters: tuple[object, ...] = ()
            if person_id is not None:
                if person_id < 1:
                    raise PersonResolutionError("person_id must be positive")
                query += " WHERE person_id = ?"
                parameters = (person_id,)
            rows = connection.execute(query + " ORDER BY id", parameters).fetchall()
            stale = 0
            checked = 0
            for row in rows:
                checked += 1
                current = {
                    str(anomaly["fingerprint"])
                    for anomaly in _current_anomalies(connection, int(row["person_id"]))
                }
                if (
                    row["status"] != DispositionStatus.STALE.value
                    and str(row["anomaly_fingerprint"]) not in current
                ):
                    connection.execute(
                        "UPDATE person_anomaly_dispositions SET status = 'stale', stale_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ? AND status = ?",
                        (int(row["id"]), str(row["status"])),
                    )
                    if connection.execute("SELECT changes()").fetchone()[0] == 1:
                        connection.execute(
                            "INSERT INTO person_anomaly_disposition_history (disposition_id, person_id, anomaly_code, anomaly_fingerprint, previous_status, new_status, actor, note) VALUES (?, ?, ?, ?, ?, 'stale', ?, ?)",
                            (
                                int(row["id"]),
                                int(row["person_id"]),
                                row["anomaly_code"],
                                row["anomaly_fingerprint"],
                                row["status"],
                                actor.strip(),
                                "fingerprint no longer present in current triage",
                            ),
                        )
                        stale += 1
            return {"checked": checked, "marked_stale": stale}
    except sqlite3.IntegrityError as exc:
        raise PersonResolutionError(
            f"disposition sync violated a database constraint: {exc}"
        ) from exc
    except sqlite3.Error as exc:
        raise PersonResolutionError(f"disposition sync failed: {exc}") from exc


def list_dispositions(
    connection: sqlite3.Connection,
    *,
    person_id: int | None = None,
    anomaly_code: str | None = None,
    status: DispositionStatus | None = None,
    include_stale: bool = False,
    actor: str | None = None,
    limit: int | None = None,
) -> list[dict[str, object]]:
    conditions: list[str] = []
    parameters: list[object] = []
    if person_id is not None:
        if person_id < 1:
            raise PersonResolutionError("person_id must be positive")
        conditions.append("d.person_id = ?")
        parameters.append(person_id)
    if anomaly_code:
        conditions.append("d.anomaly_code = ?")
        parameters.append(anomaly_code)
    if status is not None:
        conditions.append("d.status = ?")
        parameters.append(status.value)
    if not include_stale:
        conditions.append("d.status <> 'stale'")
    if actor:
        conditions.append("d.reviewer_actor = ?")
        parameters.append(actor.strip())
    query = "SELECT d.id AS disposition_id, d.person_id, d.anomaly_code, d.anomaly_fingerprint, d.status, d.reviewer_actor, d.reviewer_note, d.created_at, d.updated_at, d.acknowledged_at, d.dismissed_at, d.reopened_at, d.stale_at FROM person_anomaly_dispositions AS d"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY CASE WHEN d.status = 'stale' THEN 1 ELSE 0 END, d.person_id, d.anomaly_code, d.id"
    if limit is not None:
        if limit < 1:
            raise PersonResolutionError("limit must be positive")
        query += " LIMIT ?"
        parameters.append(limit)
    try:
        return [
            dict(row) for row in connection.execute(query, tuple(parameters)).fetchall()
        ]
    except sqlite3.Error as exc:
        raise PersonResolutionError(f"disposition listing failed: {exc}") from exc


def show_disposition(
    connection: sqlite3.Connection, disposition_id: int
) -> dict[str, object]:
    if disposition_id < 1:
        raise PersonResolutionError("disposition_id must be positive")
    try:
        row = connection.execute(
            "SELECT * FROM person_anomaly_dispositions WHERE id = ?", (disposition_id,)
        ).fetchone()
        if row is None:
            raise PersonResolutionError(f"Disposition not found: {disposition_id}")
        history = connection.execute(
            "SELECT * FROM person_anomaly_disposition_history WHERE disposition_id = ? ORDER BY id",
            (disposition_id,),
        ).fetchall()
        from canada_funeral_intel.people.triage import TriageFilters, triage_people

        current = [
            item
            for item in triage_people(
                connection,
                TriageFilters(person_id=int(row["person_id"]), include_historical=True),
            )[0]["anomalies"]
            if item["code"] == row["anomaly_code"]
            and fingerprint_anomaly(int(row["person_id"]), item)
            == row["anomaly_fingerprint"]
        ]
        return {
            "disposition": dict(row),
            "current_anomaly": current[0] if current else None,
            "history": [dict(item) for item in history],
        }
    except sqlite3.Error as exc:
        raise PersonResolutionError(f"disposition lookup failed: {exc}") from exc


def disposition_history(
    connection: sqlite3.Connection, disposition_id: int
) -> list[dict[str, object]]:
    if disposition_id < 1:
        raise PersonResolutionError("disposition_id must be positive")
    try:
        return [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM person_anomaly_disposition_history WHERE disposition_id = ? ORDER BY id",
                (disposition_id,),
            ).fetchall()
        ]
    except sqlite3.Error as exc:
        raise PersonResolutionError(
            f"disposition history lookup failed: {exc}"
        ) from exc


def dispositions_for_fingerprints(
    connection: sqlite3.Connection, keys: list[tuple[int, str, str]]
) -> dict[tuple[int, str, str], dict[str, object]]:
    if not keys:
        return {}
    clauses = " OR ".join(
        "(person_id = ? AND anomaly_code = ? AND anomaly_fingerprint = ?)" for _ in keys
    )
    parameters = tuple(value for key in keys for value in key)
    rows = connection.execute(
        f"SELECT id AS disposition_id, person_id, anomaly_code, anomaly_fingerprint, status, reviewer_actor, updated_at FROM person_anomaly_dispositions WHERE {clauses}",
        parameters,
    ).fetchall()
    return {
        (
            int(row["person_id"]),
            str(row["anomaly_code"]),
            str(row["anomaly_fingerprint"]),
        ): dict(row)
        for row in rows
    }
