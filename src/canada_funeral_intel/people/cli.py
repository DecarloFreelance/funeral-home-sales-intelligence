from __future__ import annotations

import json
import sqlite3

from canada_funeral_intel.people.models import PersonResolutionError, PersonReviewStatus
from canada_funeral_intel.people.resolution import (
    apply_person_review_decision,
    list_people,
    list_person_review_queue,
    resolve_accepted_observation,
    show_person,
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


def print_people_payload(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))
