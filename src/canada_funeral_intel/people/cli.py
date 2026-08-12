from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from canada_funeral_intel.people.audit import (
    audit_people_list,
    audit_person,
    export_people_csv,
)
from canada_funeral_intel.people.dispositions import (
    decide_disposition,
    disposition_history,
    list_dispositions,
    show_disposition,
    sync_dispositions,
)
from canada_funeral_intel.people.merge import merge_people, rollback_person_merge
from canada_funeral_intel.people.models import (
    PersonMergeDecision,
    PersonResolutionError,
    PersonReviewStatus,
)
from canada_funeral_intel.people.remediation import (
    create_task,
    list_tasks,
    show_task,
    sync_tasks,
    task_history,
    update_task,
)
from canada_funeral_intel.people.resolution import (
    apply_person_review_decision,
    list_people,
    list_person_review_queue,
    resolve_accepted_observation,
    show_person,
)
from canada_funeral_intel.people.triage import TriageFilters, triage_people


class PeopleCommandError(RuntimeError):
    """Raised when a canonical people command cannot complete safely."""


def run_people_review_populate(connection: sqlite3.Connection) -> dict[str, int]:
    from canada_funeral_intel.people.resolution import populate_person_review_queue

    try:
        inserted, unchanged = populate_person_review_queue(connection)
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc
    return {"queue_entries_inserted": inserted, "queue_entries_unchanged": unchanged}


def run_people_review_list(connection: sqlite3.Connection, status: PersonReviewStatus | None) -> list[dict[str, object]]:
    try:
        return [dict(row) for row in list_person_review_queue(connection, status=status)]
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc


def run_people_review_decide(connection: sqlite3.Connection, *, queue_id: int, status: PersonReviewStatus, note: str | None) -> dict[str, object]:
    try:
        result = apply_person_review_decision(connection, queue_id=queue_id, status=status, reviewer_note=note)
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc
    return {"queue_id": result.queue_id, "observation_id": result.observation_id, "status": result.status.value, "reviewed_at": result.reviewed_at}


def run_people_list(connection: sqlite3.Connection, entity_id: int | None) -> list[dict[str, object]]:
    try:
        return [{"person_id": p.person_id, "canonical_name": p.canonical_name, "normalized_name": p.normalized_name, "status": p.status.value} for p in list_people(connection, entity_id=entity_id)]
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc


def run_people_show(connection: sqlite3.Connection, person_id: int) -> dict[str, object]:
    try:
        return show_person(connection, person_id)
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc


def run_people_resolve(connection: sqlite3.Connection, observation_id: int) -> dict[str, object]:
    try:
        person_id = resolve_accepted_observation(connection, observation_id)
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc
    return {"observation_id": observation_id, "person_id": person_id}


def run_people_merge(connection: sqlite3.Connection, *, survivor_person_id: int, absorbed_person_id: int, reason: str, actor: str = "manual_cli") -> dict[str, object]:
    try:
        result = merge_people(connection, PersonMergeDecision(survivor_person_id, absorbed_person_id, actor, reason))
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc
    return {
        "merge_id": result.merge_history_id,
        "survivor_person_id": result.survivor_person_id,
        "absorbed_person_id": result.absorbed_person_id,
        "survivor_status": "active",
        "absorbed_status": "merged",
        "affiliations_moved": result.affiliations_moved,
        "affiliations_deduplicated": result.affiliations_deduplicated,
        "contacts_moved": result.contacts_moved,
        "contacts_deduplicated": result.contacts_deduplicated,
        "evidence_moved": result.evidence_moved,
        "evidence_deduplicated": result.evidence_deduplicated,
        "created_at": result.created_at,
    }


def run_people_rollback(connection: sqlite3.Connection, *, merge_id: int, reason: str, actor: str = "manual_cli") -> dict[str, object]:
    try:
        result = rollback_person_merge(connection, merge_id, actor=actor, reason=reason)
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc
    return {
        "merge_id": result.merge_history_id,
        "survivor_person_id": result.survivor_person_id,
        "restored_person_id": result.restored_person_id,
        "restored_affiliations": result.restored_affiliations,
        "restored_contacts": result.restored_contacts,
        "restored_evidence": result.restored_evidence,
        "rolled_back_at": result.rolled_back_at,
    }


def run_people_audit(connection: sqlite3.Connection, person_id: int) -> dict[str, object]:
    try:
        return audit_person(connection, person_id)
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc


def run_people_audit_list(connection: sqlite3.Connection, *, include_historical: bool = False) -> list[dict[str, object]]:
    try:
        return audit_people_list(connection, include_historical=include_historical)
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc


def run_people_export(connection: sqlite3.Connection, *, output: Path, include_historical: bool = False) -> dict[str, object]:
    try:
        paths = export_people_csv(connection, output, include_historical=include_historical)
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc
    return {"format": "csv", "output": str(output), "files": [path.name for path in paths]}


def run_people_triage(connection: sqlite3.Connection, filters: TriageFilters) -> list[dict[str, object]]:
    try:
        return triage_people(connection, filters)
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc


def run_anomaly_review_list(connection: sqlite3.Connection, **kwargs: object) -> list[dict[str, object]]:
    try:
        return list_dispositions(connection, **kwargs)
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc


def run_anomaly_review_show(connection: sqlite3.Connection, disposition_id: int) -> dict[str, object]:
    try:
        return show_disposition(connection, disposition_id)
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc


def run_anomaly_review_history(connection: sqlite3.Connection, disposition_id: int) -> list[dict[str, object]]:
    try:
        return disposition_history(connection, disposition_id)
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc


def run_anomaly_review_decide(connection: sqlite3.Connection, **kwargs: object) -> dict[str, object]:
    try:
        result = decide_disposition(connection, **kwargs)
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc
    return {
        "disposition_id": result.disposition_id,
        "person_id": result.person_id,
        "anomaly_code": result.anomaly_code,
        "anomaly_fingerprint": result.anomaly_fingerprint,
        "status": result.status.value,
        "actor": result.actor,
        "note": result.note,
        "changed_at": result.changed_at,
        "changed": result.changed,
    }


def run_anomaly_sync(connection: sqlite3.Connection, *, person_id: int | None, actor: str) -> dict[str, int]:
    try:
        return sync_dispositions(connection, person_id=person_id, actor=actor)
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc


def run_remediation_create(connection: sqlite3.Connection, **kwargs: object) -> dict[str, object]:
    try:
        result = create_task(connection, **kwargs)
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc
    return {"task_id": result.task_id, "person_id": result.person_id, "anomaly_code": result.anomaly_code, "anomaly_fingerprint": result.anomaly_fingerprint, "status": result.status.value, "actor": result.actor, "changed": result.changed}


def run_remediation_update(connection: sqlite3.Connection, **kwargs: object) -> dict[str, object]:
    try:
        result = update_task(connection, **kwargs)
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc
    return {"task_id": result.task_id, "person_id": result.person_id, "anomaly_code": result.anomaly_code, "anomaly_fingerprint": result.anomaly_fingerprint, "status": result.status.value, "actor": result.actor, "changed": result.changed}


def run_remediation_list(connection: sqlite3.Connection, **kwargs: object) -> list[dict[str, object]]:
    try:
        return list_tasks(connection, **kwargs)
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc


def run_remediation_show(connection: sqlite3.Connection, task_id: int) -> dict[str, object]:
    try:
        return show_task(connection, task_id)
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc


def run_remediation_history(connection: sqlite3.Connection, task_id: int) -> list[dict[str, object]]:
    try:
        return task_history(connection, task_id)
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc


def run_remediation_sync(connection: sqlite3.Connection, *, person_id: int | None, actor: str) -> dict[str, int]:
    try:
        return sync_tasks(connection, person_id=person_id, actor=actor)
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc


def print_people_payload(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))
