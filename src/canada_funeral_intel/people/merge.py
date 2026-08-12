from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from canada_funeral_intel.people.models import PersonMergeDecision, PersonResolutionError, PersonStatus
from canada_funeral_intel.storage.database import transaction


@dataclass(frozen=True, slots=True)
class PersonMergeResult:
    merge_history_id: int
    survivor_person_id: int
    merged_person_id: int
    affiliations_moved: int
    affiliations_deduplicated: int
    contacts_moved: int
    contacts_deduplicated: int


@dataclass(frozen=True, slots=True)
class PersonRollbackResult:
    merge_history_id: int
    survivor_person_id: int
    restored_person_id: int
    restored_affiliations: int
    restored_contacts: int
    rolled_back_at: str


def _assert_merge_safe(connection: sqlite3.Connection, survivor_id: int, merged_id: int) -> None:
    rows = connection.execute(
        """
        SELECT person_id, entity_id
        FROM person_affiliations
        WHERE person_id IN (?, ?) AND active = 1
        """,
        (survivor_id, merged_id),
    ).fetchall()
    branch_entities = connection.execute(
        """
        SELECT DISTINCT pa.person_id, pa.entity_id
        FROM person_affiliations AS pa
        JOIN entities AS e ON e.id = pa.entity_id
        WHERE pa.person_id IN (?, ?) AND pa.active = 1 AND e.entity_type = 'branch'
        """,
        (survivor_id, merged_id),
    ).fetchall()
    survivor_branches = {int(row["entity_id"]) for row in branch_entities if int(row["person_id"]) == survivor_id}
    merged_branches = {int(row["entity_id"]) for row in branch_entities if int(row["person_id"]) == merged_id}
    if survivor_branches and merged_branches and survivor_branches.isdisjoint(merged_branches):
        raise PersonResolutionError("cross-branch person merge requires reviewed multi-location evidence")
    del rows


def merge_people(connection: sqlite3.Connection, decision: PersonMergeDecision) -> PersonMergeResult:
    decision.validate()
    try:
        with transaction(connection):
            people = connection.execute(
                "SELECT id, status FROM people WHERE id IN (?, ?) ORDER BY id",
                (decision.survivor_person_id, decision.merged_person_id),
            ).fetchall()
            if len(people) != 2:
                raise PersonResolutionError("both people must exist")
            if any(str(row["status"]) != PersonStatus.ACTIVE.value for row in people):
                raise PersonResolutionError("both people must be active")
            _assert_merge_safe(connection, decision.survivor_person_id, decision.merged_person_id)
            cursor = connection.execute(
                """
                INSERT INTO person_merge_history (
                    survivor_person_id, merged_person_id, decision_source, reason
                ) VALUES (?, ?, ?, ?)
                """,
                (decision.survivor_person_id, decision.merged_person_id, decision.decision_source.strip(), decision.reason.strip()),
            )
            history_id = int(cursor.lastrowid)
            moved_affiliations = dedup_affiliations = 0
            affiliations = connection.execute(
                "SELECT * FROM person_affiliations WHERE person_id = ? ORDER BY id",
                (decision.merged_person_id,),
            ).fetchall()
            for row in affiliations:
                existing = connection.execute(
                    """
                    SELECT id FROM person_affiliations
                    WHERE person_id = ? AND entity_id = ? AND normalized_role = ? AND branch_context = ?
                    """,
                    (decision.survivor_person_id, row["entity_id"], row["normalized_role"], row["branch_context"]),
                ).fetchone()
                connection.execute(
                    """
                    INSERT INTO person_merge_affiliation_history
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (history_id, row["id"], decision.merged_person_id, row["entity_id"], row["observed_role"], row["normalized_role"], row["branch_context"], row["confidence"], row["source_observation_id"], "deduplicated" if existing else "moved"),
                )
                if existing:
                    connection.execute("DELETE FROM person_affiliations WHERE id = ?", (row["id"],))
                    dedup_affiliations += 1
                else:
                    connection.execute("UPDATE person_affiliations SET person_id = ? WHERE id = ?", (decision.survivor_person_id, row["id"]))
                    moved_affiliations += 1
            moved_contacts = dedup_contacts = 0
            contacts = connection.execute(
                "SELECT * FROM person_contact_points WHERE person_id = ? ORDER BY id",
                (decision.merged_person_id,),
            ).fetchall()
            for row in contacts:
                existing = connection.execute(
                    """
                    SELECT id FROM person_contact_points
                    WHERE person_id = ? AND contact_type = ? AND normalized_value = ?
                    """,
                    (decision.survivor_person_id, row["contact_type"], row["normalized_value"]),
                ).fetchone()
                connection.execute(
                    """
                    INSERT INTO person_merge_contact_history
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (history_id, row["id"], decision.merged_person_id, row["contact_type"], row["observed_value"], row["normalized_value"], row["confidence"], row["source_observation_id"], "deduplicated" if existing else "moved"),
                )
                if existing:
                    connection.execute("DELETE FROM person_contact_points WHERE id = ?", (row["id"],))
                    dedup_contacts += 1
                else:
                    connection.execute("UPDATE person_contact_points SET person_id = ? WHERE id = ?", (decision.survivor_person_id, row["id"]))
                    moved_contacts += 1
            evidence = connection.execute(
                "SELECT * FROM person_evidence WHERE person_id = ? ORDER BY id",
                (decision.merged_person_id,),
            ).fetchall()
            for row in evidence:
                connection.execute("INSERT INTO person_merge_evidence_history VALUES (?, ?, ?, ?, ?, ?, ?)", (history_id, row["id"], decision.merged_person_id, row["observation_id"], row["resolution_candidate_id"], row["review_decision"]))
                connection.execute("UPDATE person_evidence SET person_id = ? WHERE id = ?", (decision.survivor_person_id, row["id"]))
            connection.execute("UPDATE people SET status = 'merged', updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?", (decision.merged_person_id,))
            return PersonMergeResult(history_id, decision.survivor_person_id, decision.merged_person_id, moved_affiliations, dedup_affiliations, moved_contacts, dedup_contacts)
    except sqlite3.IntegrityError as exc:
        raise PersonResolutionError(f"person merge violated a database constraint: {exc}") from exc
    except sqlite3.Error as exc:
        raise PersonResolutionError(f"person merge failed: {exc}") from exc


def rollback_person_merge(connection: sqlite3.Connection, merge_history_id: int) -> PersonRollbackResult:
    if merge_history_id < 1:
        raise PersonResolutionError("merge_history_id must be positive")
    try:
        with transaction(connection):
            history = connection.execute("SELECT * FROM person_merge_history WHERE id = ?", (merge_history_id,)).fetchone()
            if history is None:
                raise PersonResolutionError(f"Person merge history not found: {merge_history_id}")
            if history["rolled_back_at"] is not None:
                raise PersonResolutionError("person merge history is already rolled back")
            survivor_id = int(history["survivor_person_id"])
            merged_id = int(history["merged_person_id"])
            restored_affiliations = restored_contacts = 0
            for row in connection.execute("SELECT * FROM person_merge_affiliation_history WHERE merge_history_id = ? ORDER BY affiliation_id", (merge_history_id,)).fetchall():
                if row["action"] == "moved":
                    connection.execute("UPDATE person_affiliations SET person_id = ? WHERE id = ?", (merged_id, row["affiliation_id"]))
                else:
                    connection.execute("INSERT INTO person_affiliations (id, person_id, entity_id, observed_role, normalized_role, branch_context, confidence, source_observation_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (row["affiliation_id"], merged_id, row["entity_id"], row["observed_role"], row["normalized_role"], row["branch_context"], row["confidence"], row["source_observation_id"]))
                restored_affiliations += 1
            for row in connection.execute("SELECT * FROM person_merge_contact_history WHERE merge_history_id = ? ORDER BY contact_id", (merge_history_id,)).fetchall():
                if row["action"] == "moved":
                    connection.execute("UPDATE person_contact_points SET person_id = ? WHERE id = ?", (merged_id, row["contact_id"]))
                else:
                    connection.execute("INSERT INTO person_contact_points (id, person_id, contact_type, observed_value, normalized_value, confidence, source_observation_id) VALUES (?, ?, ?, ?, ?, ?, ?)", (row["contact_id"], merged_id, row["contact_type"], row["observed_value"], row["normalized_value"], row["confidence"], row["source_observation_id"]))
                restored_contacts += 1
            for row in connection.execute("SELECT * FROM person_merge_evidence_history WHERE merge_history_id = ? ORDER BY evidence_id", (merge_history_id,)).fetchall():
                connection.execute("UPDATE person_evidence SET person_id = ? WHERE id = ?", (merged_id, row["evidence_id"]))
            connection.execute("UPDATE people SET status = 'active', updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?", (merged_id,))
            rolled = connection.execute("UPDATE person_merge_history SET rolled_back_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?", (merge_history_id,))
            if rolled.rowcount != 1:
                raise PersonResolutionError("person merge rollback did not update history")
            timestamp = connection.execute("SELECT rolled_back_at FROM person_merge_history WHERE id = ?", (merge_history_id,)).fetchone()["rolled_back_at"]
            return PersonRollbackResult(merge_history_id, survivor_id, merged_id, restored_affiliations, restored_contacts, str(timestamp))
    except sqlite3.IntegrityError as exc:
        raise PersonResolutionError(f"person merge rollback violated a database constraint: {exc}") from exc
    except sqlite3.Error as exc:
        raise PersonResolutionError(f"person merge rollback failed: {exc}") from exc
