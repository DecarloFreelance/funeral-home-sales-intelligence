from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from canada_funeral_intel.deduplication.models import MergeDecision
from canada_funeral_intel.storage.database import transaction


class MergeError(RuntimeError):
    """Raised when an entity merge or rollback cannot complete safely."""


@dataclass(frozen=True, slots=True)
class MergeResult:
    merge_history_id: int
    survivor_entity_id: int
    merged_entity_id: int
    memberships_moved: int
    memberships_deduplicated: int
    children_reparented: int


@dataclass(frozen=True, slots=True)
class RollbackResult:
    merge_history_id: int
    survivor_entity_id: int
    restored_entity_id: int
    memberships_restored: int
    survivor_duplicates_preserved: int
    children_restored: int
    rolled_back_at: str


def merge_entities(
    connection: sqlite3.Connection,
    decision: MergeDecision,
) -> MergeResult:
    decision.validate()
    try:
        with transaction(connection):
            survivor = _load_entity(connection, decision.survivor_entity_id)
            merged = _load_entity(connection, decision.merged_entity_id)

            if survivor["status"] != "active":
                raise MergeError(
                    f"Survivor entity {decision.survivor_entity_id} is not active"
                )
            if merged["status"] != "active":
                raise MergeError(
                    f"Merged entity {decision.merged_entity_id} is not active"
                )
            if survivor["entity_type"] != merged["entity_type"]:
                raise MergeError("Entities must have the same entity_type")
            if survivor["entity_type"] == "branch" and (
                survivor["parent_entity_id"] != merged["parent_entity_id"]
            ):
                raise MergeError("Branch entities must have the same parent_entity_id")

            cursor = connection.execute(
                """
                INSERT INTO merge_history (
                    survivor_entity_id, merged_entity_id, decision_source, reason
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    decision.survivor_entity_id,
                    decision.merged_entity_id,
                    decision.decision_source.strip(),
                    decision.reason.strip(),
                ),
            )
            if cursor.lastrowid is None:
                raise MergeError("Merge history insert returned no row ID")
            history_id = int(cursor.lastrowid)

            memberships = connection.execute(
                """
                SELECT source_record_id, membership_role
                FROM entity_source_records
                WHERE entity_id = ?
                ORDER BY source_record_id
                """,
                (decision.merged_entity_id,),
            ).fetchall()

            moved = 0
            duplicates = 0
            for membership in memberships:
                source_record_id = int(membership["source_record_id"])
                role = str(membership["membership_role"])
                exists = connection.execute(
                    """
                    SELECT 1 FROM entity_source_records
                    WHERE entity_id = ? AND source_record_id = ?
                    LIMIT 1
                    """,
                    (decision.survivor_entity_id, source_record_id),
                ).fetchone()
                action = "duplicate" if exists is not None else "moved"
                connection.execute(
                    """
                    INSERT INTO merge_membership_history (
                        merge_history_id, source_record_id, membership_role, action
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (history_id, source_record_id, role, action),
                )
                if exists is None:
                    connection.execute(
                        """
                        INSERT INTO entity_source_records (
                            entity_id, source_record_id, membership_role
                        ) VALUES (?, ?, ?)
                        """,
                        (decision.survivor_entity_id, source_record_id, role),
                    )
                    moved += 1
                else:
                    duplicates += 1

            connection.execute(
                "DELETE FROM entity_source_records WHERE entity_id = ?",
                (decision.merged_entity_id,),
            )

            children = connection.execute(
                "SELECT id, parent_entity_id FROM entities WHERE parent_entity_id = ?",
                (decision.merged_entity_id,),
            ).fetchall()
            for child in children:
                connection.execute(
                    """
                    INSERT INTO merge_parent_history (
                        merge_history_id, child_entity_id, previous_parent_entity_id
                    ) VALUES (?, ?, ?)
                    """,
                    (history_id, int(child["id"]), child["parent_entity_id"]),
                )
                connection.execute(
                    """
                    UPDATE entities
                    SET parent_entity_id = ?,
                        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    WHERE id = ?
                    """,
                    (decision.survivor_entity_id, int(child["id"])),
                )

            connection.execute(
                """
                UPDATE entities
                SET status = 'merged',
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (decision.merged_entity_id,),
            )
    except sqlite3.Error as exc:
        raise MergeError(f"Entity merge database operation failed: {exc}") from exc

    return MergeResult(
        merge_history_id=history_id,
        survivor_entity_id=decision.survivor_entity_id,
        merged_entity_id=decision.merged_entity_id,
        memberships_moved=moved,
        memberships_deduplicated=duplicates,
        children_reparented=len(children),
    )


def rollback_merge(
    connection: sqlite3.Connection,
    merge_history_id: int,
) -> RollbackResult:
    if merge_history_id < 1:
        raise MergeError("merge_history_id must be a positive integer")
    try:
        with transaction(connection):
            history = connection.execute(
                """
                SELECT survivor_entity_id, merged_entity_id, rolled_back_at
                FROM merge_history WHERE id = ?
                """,
                (merge_history_id,),
            ).fetchone()
            if history is None:
                raise MergeError(f"Merge history entry not found: {merge_history_id}")
            if history["rolled_back_at"] is not None:
                raise MergeError(
                    f"Merge history entry {merge_history_id} is already rolled back"
                )

            survivor_id = int(history["survivor_entity_id"])
            merged_id = int(history["merged_entity_id"])
            merged = _load_entity(connection, merged_id)
            if merged["status"] != "merged":
                raise MergeError(f"Entity {merged_id} is not in merged status")

            membership_rows = connection.execute(
                """
                SELECT source_record_id, membership_role, action
                FROM merge_membership_history
                WHERE merge_history_id = ?
                ORDER BY source_record_id
                """,
                (merge_history_id,),
            ).fetchall()

            restored = 0
            preserved = 0
            for row in membership_rows:
                source_record_id = int(row["source_record_id"])
                if row["action"] == "moved":
                    connection.execute(
                        """
                        DELETE FROM entity_source_records
                        WHERE entity_id = ? AND source_record_id = ?
                        """,
                        (survivor_id, source_record_id),
                    )
                    restored += 1
                else:
                    preserved += 1
                connection.execute(
                    """
                    INSERT INTO entity_source_records (
                        entity_id, source_record_id, membership_role
                    ) VALUES (?, ?, ?)
                    """,
                    (merged_id, source_record_id, str(row["membership_role"])),
                )

            parent_rows = connection.execute(
                """
                SELECT child_entity_id, previous_parent_entity_id
                FROM merge_parent_history
                WHERE merge_history_id = ?
                ORDER BY child_entity_id
                """,
                (merge_history_id,),
            ).fetchall()
            for row in parent_rows:
                connection.execute(
                    """
                    UPDATE entities
                    SET parent_entity_id = ?,
                        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    WHERE id = ?
                    """,
                    (row["previous_parent_entity_id"], int(row["child_entity_id"])),
                )

            connection.execute(
                """
                UPDATE entities
                SET status = 'active',
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (merged_id,),
            )
            connection.execute(
                """
                UPDATE merge_history
                SET rolled_back_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (merge_history_id,),
            )
            updated = connection.execute(
                "SELECT rolled_back_at FROM merge_history WHERE id = ?",
                (merge_history_id,),
            ).fetchone()
            if updated is None or updated["rolled_back_at"] is None:
                raise MergeError("Rollback did not produce rolled_back_at")
            rolled_back_at = str(updated["rolled_back_at"])
    except sqlite3.Error as exc:
        raise MergeError(f"Merge rollback database operation failed: {exc}") from exc

    return RollbackResult(
        merge_history_id=merge_history_id,
        survivor_entity_id=survivor_id,
        restored_entity_id=merged_id,
        memberships_restored=restored,
        survivor_duplicates_preserved=preserved,
        children_restored=len(parent_rows),
        rolled_back_at=rolled_back_at,
    )


def _load_entity(connection: sqlite3.Connection, entity_id: int) -> sqlite3.Row:
    row = connection.execute(
        "SELECT id, entity_type, parent_entity_id, status FROM entities WHERE id = ?",
        (entity_id,),
    ).fetchone()
    if row is None:
        raise MergeError(f"Entity not found: {entity_id}")
    return row
