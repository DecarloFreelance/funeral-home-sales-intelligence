from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from canada_funeral_intel.deduplication.merge import (
    MergeError,
    merge_entities,
    rollback_merge,
)
from canada_funeral_intel.deduplication.models import MergeDecision
from canada_funeral_intel.storage import database_session
from canada_funeral_intel.storage.migrations import apply_pending_migrations

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "database" / "migrations"


def _prepare(connection: sqlite3.Connection) -> None:
    result = apply_pending_migrations(connection, MIGRATIONS)
    assert result.status.current_version == 19
    connection.execute(
        "INSERT INTO source_datasets (id, name, source_type, jurisdiction, is_active) VALUES (1, 'Fixture Source', 'manual', 'AB', 1)"
    )


def _source(connection: sqlite3.Connection, external_id: str) -> int:
    cursor = connection.execute(
        """
        INSERT INTO source_records (
            source_dataset_id, external_record_id, raw_payload, payload_format,
            source_url, retrieved_at, checksum
        ) VALUES (1, ?, '{}', 'json', 'https://example.test/record',
                  '2026-08-08T00:00:00+00:00', ?)
        """,
        (external_id, f"checksum-{external_id}"),
    )
    assert cursor.lastrowid is not None
    return int(cursor.lastrowid)


def _entity(
    connection: sqlite3.Connection,
    name: str,
    *,
    entity_type: str = "organization",
    parent_entity_id: int | None = None,
) -> int:
    cursor = connection.execute(
        "INSERT INTO entities (entity_type, canonical_name, parent_entity_id) VALUES (?, ?, ?)",
        (entity_type, name, parent_entity_id),
    )
    assert cursor.lastrowid is not None
    return int(cursor.lastrowid)


def _member(
    connection: sqlite3.Connection,
    entity_id: int,
    source_record_id: int,
    role: str = "location",
) -> None:
    connection.execute(
        "INSERT INTO entity_source_records (entity_id, source_record_id, membership_role) VALUES (?, ?, ?)",
        (entity_id, source_record_id, role),
    )


def test_merge_moves_memberships_and_records_history(tmp_path: Path) -> None:
    database_path = tmp_path / "merge.sqlite3"
    with database_session(database_path) as connection:
        _prepare(connection)
        left = _source(connection, "left")
        right = _source(connection, "right")
        survivor = _entity(connection, "Survivor")
        merged = _entity(connection, "Merged")
        _member(connection, survivor, left)
        _member(connection, merged, right)
        connection.commit()
        result = merge_entities(
            connection,
            MergeDecision(
                survivor, merged, "manual_review", "same organization confirmed"
            ),
        )
        assert result.memberships_moved == 1
        assert (
            connection.execute(
                "SELECT status FROM entities WHERE id = ?", (merged,)
            ).fetchone()[0]
            == "merged"
        )
        members = connection.execute(
            "SELECT source_record_id FROM entity_source_records WHERE entity_id = ? ORDER BY source_record_id",
            (survivor,),
        ).fetchall()
        assert [row[0] for row in members] == [left, right]
        history = connection.execute(
            "SELECT decision_source, reason FROM merge_history WHERE id = ?",
            (result.merge_history_id,),
        ).fetchone()
        assert tuple(history) == ("manual_review", "same organization confirmed")


def test_merge_deduplicates_and_rollback_preserves_survivor(tmp_path: Path) -> None:
    database_path = tmp_path / "merge.sqlite3"
    with database_session(database_path) as connection:
        _prepare(connection)
        shared = _source(connection, "shared")
        unique = _source(connection, "unique")
        survivor = _entity(connection, "Survivor")
        merged = _entity(connection, "Merged")
        _member(connection, survivor, shared)
        _member(connection, merged, shared)
        _member(connection, merged, unique)
        connection.commit()
        result = merge_entities(
            connection, MergeDecision(survivor, merged, "automatic", "fixture")
        )
        assert result.memberships_moved == 1
        assert result.memberships_deduplicated == 1
        rollback = rollback_merge(connection, result.merge_history_id)
        assert rollback.memberships_restored == 1
        assert rollback.survivor_duplicates_preserved == 1
        survivor_members = connection.execute(
            "SELECT source_record_id FROM entity_source_records WHERE entity_id = ? ORDER BY source_record_id",
            (survivor,),
        ).fetchall()
        merged_members = connection.execute(
            "SELECT source_record_id FROM entity_source_records WHERE entity_id = ? ORDER BY source_record_id",
            (merged,),
        ).fetchall()
        assert [row[0] for row in survivor_members] == [shared]
        assert [row[0] for row in merged_members] == [shared, unique]


def test_organization_merge_reparents_children_and_rollback_restores(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "merge.sqlite3"
    with database_session(database_path) as connection:
        _prepare(connection)
        survivor = _entity(connection, "Survivor")
        merged = _entity(connection, "Merged")
        child = _entity(
            connection, "Branch", entity_type="branch", parent_entity_id=merged
        )
        connection.commit()
        result = merge_entities(
            connection, MergeDecision(survivor, merged, "manual", "fixture")
        )
        assert result.children_reparented == 1
        assert (
            connection.execute(
                "SELECT parent_entity_id FROM entities WHERE id = ?", (child,)
            ).fetchone()[0]
            == survivor
        )
        rollback = rollback_merge(connection, result.merge_history_id)
        assert rollback.children_restored == 1
        assert (
            connection.execute(
                "SELECT parent_entity_id FROM entities WHERE id = ?", (child,)
            ).fetchone()[0]
            == merged
        )


def test_branch_merge_requires_same_parent(tmp_path: Path) -> None:
    database_path = tmp_path / "merge.sqlite3"
    with database_session(database_path) as connection:
        _prepare(connection)
        parent_a = _entity(connection, "Parent A")
        parent_b = _entity(connection, "Parent B")
        survivor = _entity(
            connection, "Branch A", entity_type="branch", parent_entity_id=parent_a
        )
        merged = _entity(
            connection, "Branch B", entity_type="branch", parent_entity_id=parent_b
        )
        connection.commit()
        with pytest.raises(MergeError, match="same parent"):
            merge_entities(
                connection, MergeDecision(survivor, merged, "manual", "fixture")
            )


def test_cross_type_merge_is_rejected(tmp_path: Path) -> None:
    database_path = tmp_path / "merge.sqlite3"
    with database_session(database_path) as connection:
        _prepare(connection)
        organization = _entity(connection, "Organization")
        branch = _entity(connection, "Branch", entity_type="branch")
        connection.commit()
        with pytest.raises(MergeError, match="same entity_type"):
            merge_entities(
                connection, MergeDecision(organization, branch, "manual", "fixture")
            )


def test_rollback_is_single_use(tmp_path: Path) -> None:
    database_path = tmp_path / "merge.sqlite3"
    with database_session(database_path) as connection:
        _prepare(connection)
        survivor = _entity(connection, "Survivor")
        merged = _entity(connection, "Merged")
        connection.commit()
        result = merge_entities(
            connection, MergeDecision(survivor, merged, "manual", "fixture")
        )
        rollback_merge(connection, result.merge_history_id)
        with pytest.raises(MergeError, match="already rolled back"):
            rollback_merge(connection, result.merge_history_id)
