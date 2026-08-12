from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from canada_funeral_intel.people.models import (
    PersonMergeDecision,
    PersonResolutionError,
    PersonStatus,
)
from canada_funeral_intel.storage.database import transaction


@dataclass(frozen=True, slots=True)
class PersonMergeResult:
    merge_history_id: int
    survivor_person_id: int
    absorbed_person_id: int
    affiliations_moved: int
    affiliations_deduplicated: int
    contacts_moved: int
    contacts_deduplicated: int
    evidence_moved: int
    evidence_deduplicated: int
    created_at: str


@dataclass(frozen=True, slots=True)
class PersonRollbackResult:
    merge_history_id: int
    survivor_person_id: int
    restored_person_id: int
    restored_affiliations: int
    restored_contacts: int
    restored_evidence: int
    rolled_back_at: str


def _load_active_people(connection: sqlite3.Connection, survivor_id: int, absorbed_id: int) -> None:
    rows = connection.execute(
        "SELECT id, status FROM people WHERE id IN (?, ?) ORDER BY id",
        (survivor_id, absorbed_id),
    ).fetchall()
    if len(rows) != 2:
        raise PersonResolutionError("both people must exist")
    if any(str(row["status"]) != PersonStatus.ACTIVE.value for row in rows):
        raise PersonResolutionError("both people must be active")


def _assert_merge_safe(connection: sqlite3.Connection, survivor_id: int, absorbed_id: int) -> None:
    affiliations = connection.execute(
        "SELECT person_id, entity_id FROM person_affiliations WHERE person_id IN (?, ?) AND active = 1",
        (survivor_id, absorbed_id),
    ).fetchall()
    branch_ids = {
        int(row["entity_id"])
        for row in connection.execute(
            """
            SELECT DISTINCT pa.entity_id
            FROM person_affiliations AS pa
            JOIN entities AS e ON e.id = pa.entity_id
            WHERE pa.person_id IN (?, ?) AND pa.active = 1 AND e.entity_type = 'branch'
            """,
            (survivor_id, absorbed_id),
        ).fetchall()
    }
    survivor_branches = {int(row["entity_id"]) for row in affiliations if int(row["person_id"]) == survivor_id and int(row["entity_id"]) in branch_ids}
    absorbed_branches = {int(row["entity_id"]) for row in affiliations if int(row["person_id"]) == absorbed_id and int(row["entity_id"]) in branch_ids}
    if survivor_branches and absorbed_branches and survivor_branches.isdisjoint(absorbed_branches):
        raise PersonResolutionError("cross-branch person merge requires explicit supporting evidence")

    contacts = connection.execute(
        "SELECT person_id, contact_type, normalized_value FROM person_contact_points WHERE person_id IN (?, ?) AND active = 1",
        (survivor_id, absorbed_id),
    ).fetchall()
    for contact_type in ("email", "phone"):
        survivor_values = {str(row["normalized_value"]) for row in contacts if int(row["person_id"]) == survivor_id and row["contact_type"] == contact_type}
        absorbed_values = {str(row["normalized_value"]) for row in contacts if int(row["person_id"]) == absorbed_id and row["contact_type"] == contact_type}
        if survivor_values and absorbed_values and survivor_values.isdisjoint(absorbed_values):
            raise PersonResolutionError(f"conflicting {contact_type} identities block person merge")


def merge_people(connection: sqlite3.Connection, decision: PersonMergeDecision) -> PersonMergeResult:
    decision.validate()
    try:
        with transaction(connection):
            _load_active_people(connection, decision.survivor_person_id, decision.merged_person_id)
            _assert_merge_safe(connection, decision.survivor_person_id, decision.merged_person_id)
            cursor = connection.execute(
                """
                INSERT INTO person_merge_history (survivor_person_id, merged_person_id, decision_source, reason)
                VALUES (?, ?, ?, ?)
                """,
                (decision.survivor_person_id, decision.merged_person_id, decision.decision_source.strip(), decision.reason.strip()),
            )
            history_id = int(cursor.lastrowid)
            moved_affiliations = dedup_affiliations = 0
            for row in connection.execute("SELECT * FROM person_affiliations WHERE person_id = ? ORDER BY id", (decision.merged_person_id,)).fetchall():
                existing = connection.execute(
                    "SELECT id FROM person_affiliations WHERE person_id = ? AND entity_id = ? AND normalized_role = ? AND branch_context = ?",
                    (decision.survivor_person_id, row["entity_id"], row["normalized_role"], row["branch_context"]),
                ).fetchone()
                action = "deduplicated" if existing else "moved"
                connection.execute(
                    "INSERT INTO person_merge_affiliation_history (merge_history_id, affiliation_id, previous_person_id, entity_id, observed_role, normalized_role, branch_context, confidence, source_observation_id, action, resulting_affiliation_id, previous_active) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (history_id, row["id"], decision.merged_person_id, row["entity_id"], row["observed_role"], row["normalized_role"], row["branch_context"], row["confidence"], row["source_observation_id"], action, existing["id"] if existing else row["id"], row["active"]),
                )
                if existing:
                    connection.execute("UPDATE person_affiliations SET active = 0 WHERE id = ?", (row["id"],))
                    dedup_affiliations += 1
                else:
                    connection.execute("UPDATE person_affiliations SET person_id = ? WHERE id = ?", (decision.survivor_person_id, row["id"]))
                    moved_affiliations += 1

            moved_contacts = dedup_contacts = 0
            for row in connection.execute("SELECT * FROM person_contact_points WHERE person_id = ? ORDER BY id", (decision.merged_person_id,)).fetchall():
                existing = connection.execute("SELECT id FROM person_contact_points WHERE person_id = ? AND contact_type = ? AND normalized_value = ?", (decision.survivor_person_id, row["contact_type"], row["normalized_value"])).fetchone()
                action = "deduplicated" if existing else "moved"
                connection.execute(
                    "INSERT INTO person_merge_contact_history (merge_history_id, contact_id, previous_person_id, contact_type, observed_value, normalized_value, confidence, source_observation_id, action, resulting_contact_id, previous_active) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (history_id, row["id"], decision.merged_person_id, row["contact_type"], row["observed_value"], row["normalized_value"], row["confidence"], row["source_observation_id"], action, existing["id"] if existing else row["id"], row["active"]),
                )
                if existing:
                    connection.execute("UPDATE person_contact_points SET active = 0 WHERE id = ?", (row["id"],))
                    dedup_contacts += 1
                else:
                    connection.execute("UPDATE person_contact_points SET person_id = ? WHERE id = ?", (decision.survivor_person_id, row["id"]))
                    moved_contacts += 1

            moved_evidence = dedup_evidence = 0
            for row in connection.execute("SELECT * FROM person_evidence WHERE person_id = ? ORDER BY id", (decision.merged_person_id,)).fetchall():
                existing = connection.execute("SELECT id FROM person_evidence WHERE person_id = ? AND observation_id = ?", (decision.survivor_person_id, row["observation_id"])).fetchone()
                action = "deduplicated" if existing else "moved"
                connection.execute("INSERT INTO person_merge_evidence_history (merge_history_id, evidence_id, previous_person_id, observation_id, resolution_candidate_id, review_decision, action) VALUES (?, ?, ?, ?, ?, ?, ?)", (history_id, row["id"], decision.merged_person_id, row["observation_id"], row["resolution_candidate_id"], row["review_decision"], action))
                if existing:
                    dedup_evidence += 1
                else:
                    connection.execute("UPDATE person_evidence SET person_id = ? WHERE id = ?", (decision.survivor_person_id, row["id"]))
                    moved_evidence += 1

            connection.execute("UPDATE people SET status = 'merged', updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?", (decision.merged_person_id,))
            created = connection.execute("SELECT created_at FROM person_merge_history WHERE id = ?", (history_id,)).fetchone()["created_at"]
            return PersonMergeResult(history_id, decision.survivor_person_id, decision.merged_person_id, moved_affiliations, dedup_affiliations, moved_contacts, dedup_contacts, moved_evidence, dedup_evidence, str(created))
    except sqlite3.IntegrityError as exc:
        raise PersonResolutionError(f"person merge violated a database constraint: {exc}") from exc
    except sqlite3.Error as exc:
        raise PersonResolutionError(f"person merge failed: {exc}") from exc


def rollback_person_merge(connection: sqlite3.Connection, merge_history_id: int, *, actor: str = "manual_cli", reason: str = "") -> PersonRollbackResult:
    if merge_history_id < 1:
        raise PersonResolutionError("merge_history_id must be positive")
    if not actor.strip() or not reason.strip():
        raise PersonResolutionError("rollback actor and reason are required")
    try:
        with transaction(connection):
            history = connection.execute("SELECT * FROM person_merge_history WHERE id = ?", (merge_history_id,)).fetchone()
            if history is None:
                raise PersonResolutionError(f"Person merge history not found: {merge_history_id}")
            if history["rolled_back_at"] is not None:
                raise PersonResolutionError("person merge history is already rolled back")
            survivor_id = int(history["survivor_person_id"])
            absorbed_id = int(history["merged_person_id"])
            survivor = connection.execute("SELECT status FROM people WHERE id = ?", (survivor_id,)).fetchone()
            absorbed = connection.execute("SELECT status FROM people WHERE id = ?", (absorbed_id,)).fetchone()
            if survivor is None or absorbed is None or survivor["status"] != PersonStatus.ACTIVE.value or absorbed["status"] != PersonStatus.MERGED.value:
                raise PersonResolutionError("merge state is not safely rollbackable")

            restored_affiliations = restored_contacts = restored_evidence = 0
            for row in connection.execute("SELECT * FROM person_merge_affiliation_history WHERE merge_history_id = ? AND action = 'moved' ORDER BY affiliation_id", (merge_history_id,)).fetchall():
                current = connection.execute("SELECT person_id, entity_id, normalized_role, branch_context, source_observation_id FROM person_affiliations WHERE id = ?", (row["affiliation_id"],)).fetchone()
                if current is None or int(current["person_id"]) != survivor_id or tuple(current[x] for x in ("entity_id", "normalized_role", "branch_context", "source_observation_id")) != tuple(row[x] for x in ("entity_id", "normalized_role", "branch_context", "source_observation_id")):
                    raise PersonResolutionError("affiliation changed after merge; rollback is unsafe")
                connection.execute("UPDATE person_affiliations SET person_id = ? WHERE id = ?", (absorbed_id, row["affiliation_id"]))
                restored_affiliations += 1
            for row in connection.execute("SELECT * FROM person_merge_affiliation_history WHERE merge_history_id = ? AND action = 'deduplicated' ORDER BY affiliation_id", (merge_history_id,)).fetchall():
                current = connection.execute("SELECT person_id, active FROM person_affiliations WHERE id = ?", (row["affiliation_id"],)).fetchone()
                if current is None or int(current["person_id"]) != absorbed_id or int(current["active"]) != 0:
                    raise PersonResolutionError("deduplicated affiliation changed after merge; rollback is unsafe")
                connection.execute("UPDATE person_affiliations SET active = ? WHERE id = ?", (row["previous_active"], row["affiliation_id"]))
                restored_affiliations += 1
            for row in connection.execute("SELECT * FROM person_merge_contact_history WHERE merge_history_id = ? AND action = 'moved' ORDER BY contact_id", (merge_history_id,)).fetchall():
                current = connection.execute("SELECT person_id, contact_type, normalized_value, source_observation_id FROM person_contact_points WHERE id = ?", (row["contact_id"],)).fetchone()
                if current is None or int(current["person_id"]) != survivor_id or tuple(current[x] for x in ("contact_type", "normalized_value", "source_observation_id")) != tuple(row[x] for x in ("contact_type", "normalized_value", "source_observation_id")):
                    raise PersonResolutionError("contact point changed after merge; rollback is unsafe")
                connection.execute("UPDATE person_contact_points SET person_id = ? WHERE id = ?", (absorbed_id, row["contact_id"]))
                restored_contacts += 1
            for row in connection.execute("SELECT * FROM person_merge_contact_history WHERE merge_history_id = ? AND action = 'deduplicated' ORDER BY contact_id", (merge_history_id,)).fetchall():
                current = connection.execute("SELECT person_id, active FROM person_contact_points WHERE id = ?", (row["contact_id"],)).fetchone()
                if current is None or int(current["person_id"]) != absorbed_id or int(current["active"]) != 0:
                    raise PersonResolutionError("deduplicated contact changed after merge; rollback is unsafe")
                connection.execute("UPDATE person_contact_points SET active = ? WHERE id = ?", (row["previous_active"], row["contact_id"]))
                restored_contacts += 1
            for row in connection.execute("SELECT * FROM person_merge_evidence_history WHERE merge_history_id = ? AND action = 'moved' ORDER BY evidence_id", (merge_history_id,)).fetchall():
                current = connection.execute("SELECT person_id, observation_id FROM person_evidence WHERE id = ?", (row["evidence_id"],)).fetchone()
                if current is None or int(current["person_id"]) != survivor_id or int(current["observation_id"]) != int(row["observation_id"]):
                    raise PersonResolutionError("evidence changed after merge; rollback is unsafe")
                connection.execute("UPDATE person_evidence SET person_id = ? WHERE id = ?", (absorbed_id, row["evidence_id"]))
                restored_evidence += 1
            connection.execute("UPDATE people SET status = 'active', updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?", (absorbed_id,))
            connection.execute("UPDATE person_merge_history SET rolled_back_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), rollback_actor = ?, rollback_reason = ? WHERE id = ?", (actor.strip(), reason.strip(), merge_history_id))
            timestamp = connection.execute("SELECT rolled_back_at FROM person_merge_history WHERE id = ?", (merge_history_id,)).fetchone()["rolled_back_at"]
            return PersonRollbackResult(merge_history_id, survivor_id, absorbed_id, restored_affiliations, restored_contacts, restored_evidence, str(timestamp))
    except sqlite3.IntegrityError as exc:
        raise PersonResolutionError(f"person merge rollback violated a database constraint: {exc}") from exc
    except sqlite3.Error as exc:
        raise PersonResolutionError(f"person merge rollback failed: {exc}") from exc
