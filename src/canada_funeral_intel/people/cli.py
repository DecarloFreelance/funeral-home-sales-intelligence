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
    person_review_backlog,
    resolve_accepted_observation,
    show_person,
)
from canada_funeral_intel.people.triage import TriageFilters, triage_people
from canada_funeral_intel.people.work_queue import (
    WorkQueueFilters,
    export_work_queue_csv,
    list_work_queue,
    owner_workload,
    show_work_item,
)


class PeopleCommandError(RuntimeError):
    """Raised when a canonical people command cannot complete safely."""


def run_people_review_populate(connection: sqlite3.Connection) -> dict[str, int]:
    from canada_funeral_intel.people.resolution import populate_person_review_queue

    try:
        inserted, unchanged = populate_person_review_queue(connection)
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc
    return {"queue_entries_inserted": inserted, "queue_entries_unchanged": unchanged}


def run_people_review_list(
    connection: sqlite3.Connection, status: PersonReviewStatus | None
) -> list[dict[str, object]]:
    try:
        return [
            dict(row) for row in list_person_review_queue(connection, status=status)
        ]
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc


def run_people_review_backlog(
    connection: sqlite3.Connection,
    *,
    include_details: bool = False,
) -> dict[str, object]:
    try:
        return person_review_backlog(connection, include_details=include_details)
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc


def run_people_review_decide(
    connection: sqlite3.Connection,
    *,
    queue_id: int,
    status: PersonReviewStatus,
    note: str | None,
) -> dict[str, object]:
    try:
        result = apply_person_review_decision(
            connection, queue_id=queue_id, status=status, reviewer_note=note
        )
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc
    return {
        "queue_id": result.queue_id,
        "observation_id": result.observation_id,
        "status": result.status.value,
        "reviewed_at": result.reviewed_at,
    }


def run_people_review_auto_triage(
    connection: sqlite3.Connection, *, apply_safe: bool = False
) -> dict[str, object]:
    """Recommend safe reject/defer decisions for obvious extractor output."""
    pending = list_person_review_queue(
        connection, status=PersonReviewStatus.PENDING
    )
    role_only = {
        "funeral director",
        "vice president",
        "managing funeral director",
        "operations supervisor",
        "funeral director embalmer",
        "past president",
    }
    reject_prefixes = (
        "contact us",
        "our caring staff",
        "our vision mission values",
        "about us at brockie",
        "difficulty.",
        "grieving by dr.",
    )
    decisions: list[dict[str, object]] = []
    applied = 0
    for row in pending:
        name = str(row["normalized_name"]).strip().casefold()
        source_url = str(row["source_url"])
        status: PersonReviewStatus | None = None
        reason = ""
        if name in role_only or name in {
            "winnipeg’s oldest family owned",
            "bardal funeral home crematorium",
        }:
            status = PersonReviewStatus.REJECTED
            reason = "obvious extractor noise or business/role text"
        elif any(name.startswith(prefix) for prefix in reject_prefixes):
            status = PersonReviewStatus.REJECTED
            reason = "page heading, contact block, or article text"
        elif "/history" in source_url:
            status = PersonReviewStatus.REJECTED
            reason = "historical ownership/history evidence; exclude from current personnel"
        elif name in {
            "patricia a. sweryd vice",
            "david e. pritchard past",
            "michelle klemick office",
            "cindy anderson funeral service",
            "shelley wray grief seminar",
            "kim lewarne funeral celebrant",
            "wade kelly lumbard wade",
            "jack joyce lumbard jack",
        }:
            status = PersonReviewStatus.DEFERRED
            reason = "named candidate needs manual cleanup before resolution"
        if status is None:
            continue
        decision = {
            "queue_id": row["queue_id"],
            "observation_id": row["observation_id"],
            "observed_name": row["observed_name"],
            "recommendation": status.value,
            "reason": reason,
        }
        if apply_safe:
            apply_person_review_decision(
                connection,
                queue_id=int(row["queue_id"]),
                status=status,
                reviewer_note=f"Safe auto-triage: {reason}.",
            )
            applied += 1
        decisions.append(decision)
    return {
        "dry_run": not apply_safe,
        "pending_considered": len(pending),
        "recommendations": len(decisions),
        "applied": applied,
        "decisions": decisions,
    }


def run_people_review_agent(
    connection: sqlite3.Connection,
    *,
    model: str,
    output: Path | None,
    provider: str = "openai",
    keys_file: Path | None = None,
    agent: str = "people-review",
    queue_limit: int = 10,
    apply_safe: bool = False,
    minimum_confidence: float = 0.95,
) -> dict[str, object]:
    from canada_funeral_intel.people.agent_review import (
        AgentReviewError,
        review_deferred_people,
    )

    try:
        return review_deferred_people(
            connection,
            model=model,
            output_path=output,
            provider=provider,
            keys_file=keys_file,
            agent=agent,
            queue_limit=queue_limit,
            apply_safe=apply_safe,
            minimum_confidence=minimum_confidence,
        )
    except AgentReviewError as exc:
        raise PeopleCommandError(str(exc)) from exc


def run_people_list(
    connection: sqlite3.Connection, entity_id: int | None
) -> list[dict[str, object]]:
    try:
        return [
            {
                "person_id": p.person_id,
                "canonical_name": p.canonical_name,
                "normalized_name": p.normalized_name,
                "status": p.status.value,
            }
            for p in list_people(connection, entity_id=entity_id)
        ]
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc


def run_people_show(
    connection: sqlite3.Connection, person_id: int
) -> dict[str, object]:
    try:
        return show_person(connection, person_id)
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc


def run_people_resolve(
    connection: sqlite3.Connection, observation_id: int
) -> dict[str, object]:
    try:
        person_id = resolve_accepted_observation(connection, observation_id)
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc
    return {"observation_id": observation_id, "person_id": person_id}


def run_people_merge(
    connection: sqlite3.Connection,
    *,
    survivor_person_id: int,
    absorbed_person_id: int,
    reason: str,
    actor: str = "manual_cli",
) -> dict[str, object]:
    try:
        result = merge_people(
            connection,
            PersonMergeDecision(survivor_person_id, absorbed_person_id, actor, reason),
        )
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


def run_people_rollback(
    connection: sqlite3.Connection,
    *,
    merge_id: int,
    reason: str,
    actor: str = "manual_cli",
) -> dict[str, object]:
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


def run_people_audit(
    connection: sqlite3.Connection, person_id: int
) -> dict[str, object]:
    try:
        return audit_person(connection, person_id)
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc


def run_people_audit_list(
    connection: sqlite3.Connection, *, include_historical: bool = False
) -> list[dict[str, object]]:
    try:
        return audit_people_list(connection, include_historical=include_historical)
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc


def run_people_export(
    connection: sqlite3.Connection, *, output: Path, include_historical: bool = False
) -> dict[str, object]:
    try:
        paths = export_people_csv(
            connection, output, include_historical=include_historical
        )
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc
    return {
        "format": "csv",
        "output": str(output),
        "files": [path.name for path in paths],
    }


def run_people_triage(
    connection: sqlite3.Connection, filters: TriageFilters
) -> list[dict[str, object]]:
    try:
        return triage_people(connection, filters)
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc


def run_anomaly_review_list(
    connection: sqlite3.Connection, **kwargs: object
) -> list[dict[str, object]]:
    try:
        return list_dispositions(connection, **kwargs)
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc


def run_anomaly_review_show(
    connection: sqlite3.Connection, disposition_id: int
) -> dict[str, object]:
    try:
        return show_disposition(connection, disposition_id)
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc


def run_anomaly_review_history(
    connection: sqlite3.Connection, disposition_id: int
) -> list[dict[str, object]]:
    try:
        return disposition_history(connection, disposition_id)
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc


def run_anomaly_review_decide(
    connection: sqlite3.Connection, **kwargs: object
) -> dict[str, object]:
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


def run_anomaly_sync(
    connection: sqlite3.Connection, *, person_id: int | None, actor: str
) -> dict[str, int]:
    try:
        return sync_dispositions(connection, person_id=person_id, actor=actor)
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc


def run_remediation_create(
    connection: sqlite3.Connection, **kwargs: object
) -> dict[str, object]:
    try:
        result = create_task(connection, **kwargs)
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc
    return {
        "task_id": result.task_id,
        "person_id": result.person_id,
        "anomaly_code": result.anomaly_code,
        "anomaly_fingerprint": result.anomaly_fingerprint,
        "status": result.status.value,
        "actor": result.actor,
        "changed": result.changed,
    }


def run_remediation_update(
    connection: sqlite3.Connection, **kwargs: object
) -> dict[str, object]:
    try:
        result = update_task(connection, **kwargs)
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc
    return {
        "task_id": result.task_id,
        "person_id": result.person_id,
        "anomaly_code": result.anomaly_code,
        "anomaly_fingerprint": result.anomaly_fingerprint,
        "status": result.status.value,
        "actor": result.actor,
        "changed": result.changed,
    }


def run_remediation_list(
    connection: sqlite3.Connection, **kwargs: object
) -> list[dict[str, object]]:
    try:
        return list_tasks(connection, **kwargs)
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc


def run_remediation_show(
    connection: sqlite3.Connection, task_id: int
) -> dict[str, object]:
    try:
        return show_task(connection, task_id)
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc


def run_remediation_history(
    connection: sqlite3.Connection, task_id: int
) -> list[dict[str, object]]:
    try:
        return task_history(connection, task_id)
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc


def run_remediation_sync(
    connection: sqlite3.Connection, *, person_id: int | None, actor: str
) -> dict[str, int]:
    try:
        return sync_tasks(connection, person_id=person_id, actor=actor)
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc


def run_work_queue_list(
    connection: sqlite3.Connection, filters: WorkQueueFilters
) -> list[dict[str, object]]:
    try:
        return list_work_queue(connection, filters)
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc


def run_work_queue_show(
    connection: sqlite3.Connection,
    *,
    person_id: int,
    fingerprint: str,
    include_historical: bool = False,
) -> dict[str, object]:
    try:
        return show_work_item(
            connection,
            person_id=person_id,
            fingerprint=fingerprint,
            include_historical=include_historical,
        )
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc


def run_work_queue_owners(
    connection: sqlite3.Connection, *, include_historical: bool = False
) -> list[dict[str, object]]:
    try:
        return owner_workload(connection, include_historical=include_historical)
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc


def run_work_queue_export(
    connection: sqlite3.Connection, *, output: Path, include_historical: bool = False
) -> dict[str, object]:
    try:
        paths = export_work_queue_csv(
            connection, output, include_historical=include_historical
        )
        return {
            "format": "csv",
            "output": str(output),
            "files": [path.name for path in paths],
        }
    except PersonResolutionError as exc:
        raise PeopleCommandError(str(exc)) from exc


def print_people_payload(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))
