from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from canada_funeral_intel.people.models import (
    PersonRecord,
    PersonResolutionError,
    PersonReviewStatus,
    PersonStatus,
)
from canada_funeral_intel.storage.database import transaction


@dataclass(frozen=True, slots=True)
class PersonReviewResult:
    queue_id: int
    observation_id: int
    status: PersonReviewStatus
    reviewed_at: str | None


def populate_person_review_queue(connection: sqlite3.Connection) -> tuple[int, int]:
    """Queue every immutable observation exactly once."""
    try:
        with transaction(connection):
            rows = connection.execute(
                """
                SELECT o.id, q.id AS queue_id
                FROM website_page_person_observations AS o
                LEFT JOIN person_observation_review_queue AS q
                  ON q.observation_id = o.id
                ORDER BY o.id
                """
            ).fetchall()
            inserted = 0
            unchanged = 0
            for row in rows:
                if row["queue_id"] is not None:
                    unchanged += 1
                    continue
                cursor = connection.execute(
                    """
                    INSERT INTO person_observation_review_queue (observation_id)
                    VALUES (?) ON CONFLICT(observation_id) DO NOTHING
                    """,
                    (int(row["id"]),),
                )
                inserted += cursor.rowcount
    except sqlite3.Error as exc:
        raise PersonResolutionError(
            f"person review queue population failed: {exc}"
        ) from exc
    return inserted, unchanged


def list_person_review_queue(
    connection: sqlite3.Connection,
    *,
    status: PersonReviewStatus | None = PersonReviewStatus.PENDING,
) -> tuple[dict[str, object], ...]:
    query = """
        SELECT q.id AS queue_id, q.observation_id, q.status,
               q.reviewer_note, q.created_at, q.reviewed_at,
               o.website_page_id, o.website_id, o.entity_id,
               o.observed_name, o.normalized_name, o.role_title,
               o.normalized_role, o.normalized_email, o.normalized_phone,
               o.branch_context, o.source_url, o.content_hash,
               o.extractor_version, o.evidence_snippet
        FROM person_observation_review_queue AS q
        JOIN website_page_person_observations AS o ON o.id = q.observation_id
    """
    parameters: tuple[object, ...] = ()
    if status is not None:
        query += " WHERE q.status = ?"
        parameters = (status.value,)
    query += " ORDER BY q.id"
    try:
        rows = connection.execute(query, parameters).fetchall()
    except sqlite3.Error as exc:
        raise PersonResolutionError(
            f"person review queue listing failed: {exc}"
        ) from exc
    return tuple(dict(row) for row in rows)


def person_review_backlog(
    connection: sqlite3.Connection,
    *,
    include_details: bool = False,
) -> dict[str, object]:
    """Return read-only workflow state for every person observation."""
    query = """
        SELECT o.id AS observation_id,
               o.website_page_id,
               o.website_id,
               o.entity_id,
               o.source_url,
               o.observed_name,
               q.status AS review_status,
               CASE
                   WHEN q.id IS NULL THEN 'missing_review'
                   WHEN q.status = 'pending' THEN 'pending'
                   WHEN q.status = 'deferred' THEN 'deferred'
                   WHEN q.status = 'rejected' THEN 'rejected'
                   WHEN q.status = 'accepted'
                        AND EXISTS (
                            SELECT 1
                            FROM person_evidence AS e
                            WHERE e.observation_id = o.id
                        ) THEN 'resolved'
                   WHEN q.status = 'accepted' THEN 'accepted_unresolved'
                   ELSE 'unknown'
               END AS workflow_state
        FROM website_page_person_observations AS o
        LEFT JOIN person_observation_review_queue AS q
          ON q.observation_id = o.id
        ORDER BY o.id
    """
    try:
        rows = connection.execute(query).fetchall()
    except sqlite3.Error as exc:
        raise PersonResolutionError(
            f"person review backlog lookup failed: {exc}"
        ) from exc

    counts = {
        "missing_review": 0,
        "pending": 0,
        "deferred": 0,
        "accepted_unresolved": 0,
        "rejected": 0,
        "resolved": 0,
    }
    details: list[dict[str, object]] = []
    for row in rows:
        state = str(row["workflow_state"])
        if state in counts:
            counts[state] += 1
        if include_details:
            details.append(
                {
                    "observation_id": int(row["observation_id"]),
                    "website_page_id": int(row["website_page_id"]),
                    "website_id": int(row["website_id"]),
                    "entity_id": int(row["entity_id"]),
                    "source_url": str(row["source_url"]),
                    "observed_name": str(row["observed_name"]),
                    "review_status": None
                    if row["review_status"] is None
                    else str(row["review_status"]),
                    "workflow_state": state,
                }
            )
    result: dict[str, object] = {"counts": counts}
    if include_details:
        result["observations"] = details
    return result


def apply_person_review_decision(
    connection: sqlite3.Connection,
    *,
    queue_id: int,
    status: PersonReviewStatus,
    reviewer_note: str | None = None,
) -> PersonReviewResult:
    if queue_id < 1 or status not in {
        PersonReviewStatus.ACCEPTED,
        PersonReviewStatus.REJECTED,
        PersonReviewStatus.DEFERRED,
    }:
        raise PersonResolutionError("invalid person review decision")
    note = reviewer_note.strip() if reviewer_note else None
    try:
        with transaction(connection):
            row = connection.execute(
                "SELECT observation_id, status, reviewed_at FROM person_observation_review_queue WHERE id = ?",
                (queue_id,),
            ).fetchone()
            if row is None:
                raise PersonResolutionError(
                    f"Person review entry not found: {queue_id}"
                )
            current = PersonReviewStatus(str(row["status"]))
            if current in {PersonReviewStatus.ACCEPTED, PersonReviewStatus.REJECTED}:
                raise PersonResolutionError(
                    f"Person review entry {queue_id} is already finalized as {current.value}"
                )
            updated = connection.execute(
                """
                UPDATE person_observation_review_queue
                SET status = ?, reviewer_note = ?,
                    reviewed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ? AND status IN ('pending', 'deferred')
                """,
                (status.value, note, queue_id),
            )
            if updated.rowcount != 1:
                raise PersonResolutionError(
                    "person review update did not affect one row"
                )
            reviewed = connection.execute(
                "SELECT reviewed_at FROM person_observation_review_queue WHERE id = ?",
                (queue_id,),
            ).fetchone()
            return PersonReviewResult(
                queue_id,
                int(row["observation_id"]),
                status,
                None if reviewed is None else str(reviewed["reviewed_at"]),
            )
    except sqlite3.Error as exc:
        raise PersonResolutionError(f"person review decision failed: {exc}") from exc


def list_people(
    connection: sqlite3.Connection,
    *,
    entity_id: int | None = None,
) -> tuple[PersonRecord, ...]:
    query = """
        SELECT DISTINCT p.id, p.canonical_name, p.normalized_name, p.status
        FROM people AS p
        LEFT JOIN person_affiliations AS a ON a.person_id = p.id
        WHERE p.status = 'active'
    """
    parameters: tuple[object, ...] = ()
    if entity_id is not None:
        if entity_id < 1:
            raise PersonResolutionError("entity_id must be positive")
        query += " AND a.entity_id = ?"
        parameters = (entity_id,)
    query += " ORDER BY p.normalized_name, p.id"
    try:
        rows = connection.execute(query, parameters).fetchall()
    except sqlite3.Error as exc:
        raise PersonResolutionError(f"people listing failed: {exc}") from exc
    return tuple(
        PersonRecord(
            int(r["id"]),
            str(r["canonical_name"]),
            str(r["normalized_name"]),
            PersonStatus(str(r["status"])),
        )
        for r in rows
    )


def show_person(connection: sqlite3.Connection, person_id: int) -> dict[str, object]:
    if person_id < 1:
        raise PersonResolutionError("person_id must be positive")
    try:
        person = connection.execute(
            "SELECT id, canonical_name, normalized_name, status FROM people WHERE id = ?",
            (person_id,),
        ).fetchone()
        if person is None:
            raise PersonResolutionError(f"Person not found: {person_id}")
        affiliations = connection.execute(
            "SELECT id, entity_id, observed_role, normalized_role, branch_context, confidence, source_observation_id, active FROM person_affiliations WHERE person_id = ? ORDER BY entity_id, id",
            (person_id,),
        ).fetchall()
        contacts = connection.execute(
            "SELECT id, contact_type, observed_value, normalized_value, confidence, source_observation_id, active FROM person_contact_points WHERE person_id = ? ORDER BY contact_type, normalized_value, id",
            (person_id,),
        ).fetchall()
        evidence = connection.execute(
            "SELECT id, observation_id, resolution_candidate_id, review_decision FROM person_evidence WHERE person_id = ? ORDER BY observation_id, id",
            (person_id,),
        ).fetchall()
    except sqlite3.Error as exc:
        raise PersonResolutionError(f"person lookup failed: {exc}") from exc
    return {
        "person_id": int(person["id"]),
        "canonical_name": str(person["canonical_name"]),
        "normalized_name": str(person["normalized_name"]),
        "status": str(person["status"]),
        "affiliations": [dict(r) for r in affiliations],
        "contact_points": [dict(r) for r in contacts],
        "evidence": [dict(r) for r in evidence],
    }


def _compatible_person_ids(
    connection: sqlite3.Connection, observation: sqlite3.Row
) -> list[int]:
    entity_id = int(observation["entity_id"])
    name = str(observation["normalized_name"])
    email = str(observation["normalized_email"] or "")
    phone = str(observation["normalized_phone"] or "")
    rows = connection.execute(
        """
        SELECT DISTINCT p.id
        FROM people AS p
        JOIN person_affiliations AS a ON a.person_id = p.id
        LEFT JOIN person_contact_points AS c ON c.person_id = p.id
        WHERE p.status = 'active' AND a.entity_id = ?
          AND (c.normalized_value IN (?, ?) OR p.normalized_name = ?)
        ORDER BY p.id
        """,
        (entity_id, email, phone, name),
    ).fetchall()
    ids = [int(r["id"]) for r in rows if email or phone or name]
    if not ids:
        return []
    # Email is deterministic only when the existing person has no conflicting email.
    if email:
        exact = connection.execute(
            "SELECT DISTINCT p.id FROM people p JOIN person_affiliations a ON a.person_id=p.id JOIN person_contact_points c ON c.person_id=p.id WHERE p.status='active' AND a.entity_id=? AND c.contact_type='email' AND c.normalized_value=? ORDER BY p.id",
            (entity_id, email),
        ).fetchall()
        return [int(r["id"]) for r in exact]
    if phone and name:
        exact = connection.execute(
            "SELECT DISTINCT p.id FROM people p JOIN person_affiliations a ON a.person_id=p.id JOIN person_contact_points c ON c.person_id=p.id WHERE p.status='active' AND a.entity_id=? AND p.normalized_name=? AND c.contact_type='phone' AND c.normalized_value=? ORDER BY p.id",
            (entity_id, name, phone),
        ).fetchall()
        return [int(r["id"]) for r in exact]
    return []


def resolve_accepted_observation(
    connection: sqlite3.Connection, observation_id: int
) -> int:
    if observation_id < 1:
        raise PersonResolutionError("observation_id must be positive")
    try:
        with transaction(connection):
            observation = connection.execute(
                "SELECT * FROM website_page_person_observations WHERE id = ?",
                (observation_id,),
            ).fetchone()
            if observation is None:
                raise PersonResolutionError(f"Observation not found: {observation_id}")
            review = connection.execute(
                "SELECT status FROM person_observation_review_queue WHERE observation_id = ?",
                (observation_id,),
            ).fetchone()
            if review is None or review["status"] != PersonReviewStatus.ACCEPTED.value:
                raise PersonResolutionError(
                    "observation must have an accepted person review"
                )
            existing_evidence = connection.execute(
                "SELECT person_id FROM person_evidence WHERE observation_id = ?",
                (observation_id,),
            ).fetchone()
            if existing_evidence is not None:
                return int(existing_evidence["person_id"])
            matches = _compatible_person_ids(connection, observation)
            if len(matches) > 1:
                raise PersonResolutionError(
                    "observation has conflicting canonical contact matches"
                )
            if matches:
                person_id = matches[0]
            else:
                cursor = connection.execute(
                    "INSERT INTO people (canonical_name, normalized_name) VALUES (?, ?)",
                    (observation["observed_name"], observation["normalized_name"]),
                )
                person_id = int(cursor.lastrowid)
            connection.execute(
                "INSERT OR IGNORE INTO person_affiliations (person_id, entity_id, observed_role, normalized_role, branch_context, confidence, source_observation_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    person_id,
                    observation["entity_id"],
                    observation["role_title"],
                    observation["normalized_role"],
                    observation["branch_context"] or "",
                    observation["confidence"],
                    observation_id,
                ),
            )
            for contact_type, observed, normalized in (
                ("email", observation["email"], observation["normalized_email"]),
                ("phone", observation["phone"], observation["normalized_phone"]),
            ):
                if normalized:
                    connection.execute(
                        "INSERT OR IGNORE INTO person_contact_points (person_id, contact_type, observed_value, normalized_value, confidence, source_observation_id) VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            person_id,
                            contact_type,
                            observed or normalized,
                            normalized,
                            observation["confidence"],
                            observation_id,
                        ),
                    )
            connection.execute(
                "INSERT INTO person_evidence (person_id, observation_id, review_decision) VALUES (?, ?, 'accepted')",
                (person_id, observation_id),
            )
            return person_id
    except sqlite3.IntegrityError as exc:
        raise PersonResolutionError(
            f"canonical person resolution violated a safety constraint: {exc}"
        ) from exc
    except sqlite3.Error as exc:
        raise PersonResolutionError(
            f"canonical person resolution failed: {exc}"
        ) from exc
