from __future__ import annotations

import json
import sqlite3

from canada_funeral_intel.deduplication.merge import (
    MergeError,
    merge_entities,
    rollback_merge,
)
from canada_funeral_intel.deduplication.models import MergeDecision


class MergeCommandError(RuntimeError):
    """Raised when a merge CLI command cannot complete safely."""


def run_merge_apply(
    connection: sqlite3.Connection,
    *,
    survivor_entity_id: int,
    merged_entity_id: int,
    decision_source: str,
    reason: str,
) -> dict[str, object]:
    try:
        result = merge_entities(
            connection,
            MergeDecision(
                survivor_entity_id, merged_entity_id, decision_source, reason
            ),
        )
    except (MergeError, ValueError) as exc:
        raise MergeCommandError(str(exc)) from exc
    return {
        "merge_history_id": result.merge_history_id,
        "survivor_entity_id": result.survivor_entity_id,
        "merged_entity_id": result.merged_entity_id,
        "memberships_moved": result.memberships_moved,
        "memberships_deduplicated": result.memberships_deduplicated,
        "children_reparented": result.children_reparented,
    }


def run_merge_rollback(
    connection: sqlite3.Connection, *, merge_history_id: int
) -> dict[str, object]:
    try:
        result = rollback_merge(connection, merge_history_id)
    except MergeError as exc:
        raise MergeCommandError(str(exc)) from exc
    return {
        "merge_history_id": result.merge_history_id,
        "survivor_entity_id": result.survivor_entity_id,
        "restored_entity_id": result.restored_entity_id,
        "memberships_restored": result.memberships_restored,
        "survivor_duplicates_preserved": result.survivor_duplicates_preserved,
        "children_restored": result.children_restored,
        "rolled_back_at": result.rolled_back_at,
    }


def print_merge_payload(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))
