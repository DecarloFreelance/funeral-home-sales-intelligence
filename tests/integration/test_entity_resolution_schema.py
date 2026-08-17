from __future__ import annotations

from pathlib import Path

from canada_funeral_intel.storage import database_session
from canada_funeral_intel.storage.migrations import apply_pending_migrations

ROOT = Path(__file__).resolve().parents[2]
MIGRATION_DIR = ROOT / "database" / "migrations"


def test_entity_resolution_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "entity-resolution.sqlite3"

    with database_session(database_path) as connection:
        applied = apply_pending_migrations(connection, MIGRATION_DIR)
        assert len(applied.applied) == 27

        tables = {
            row["name"]
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            )
        }

        assert {
            "entities",
            "entity_source_records",
            "match_candidates",
            "match_evidence",
            "entity_review_queue",
            "merge_history",
        } <= tables

        entity_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(entities)")
        }
        assert {
            "id",
            "entity_type",
            "canonical_name",
            "parent_entity_id",
            "status",
            "created_at",
            "updated_at",
        } == entity_columns

        candidate_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(match_candidates)")
        }
        assert {
            "id",
            "left_source_record_id",
            "right_source_record_id",
            "candidate_method",
            "score",
            "decision",
            "created_at",
            "updated_at",
        } == candidate_columns
