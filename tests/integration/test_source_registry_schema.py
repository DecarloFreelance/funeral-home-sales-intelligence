from pathlib import Path

from canada_funeral_intel.storage import database_session
from canada_funeral_intel.storage.migrations import apply_pending_migrations

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "database" / "migrations"


def test_source_registry_metadata_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "registry.sqlite3"

    with database_session(database_path) as connection:
        status = apply_pending_migrations(connection, MIGRATIONS).status

        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(source_datasets)")
        }
        indexes = {
            row["name"]
            for row in connection.execute("PRAGMA index_list(source_datasets)")
        }

    assert status.current_version == 18
    assert {
        "source_format",
        "trust_level",
        "refresh_interval_days",
        "coverage",
        "licensing_notes",
    } <= columns
    assert {
        "idx_source_datasets_type",
        "idx_source_datasets_jurisdiction",
        "idx_source_datasets_active",
    } <= indexes
