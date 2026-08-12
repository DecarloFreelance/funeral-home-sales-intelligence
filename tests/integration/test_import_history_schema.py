from pathlib import Path

from canada_funeral_intel.storage import database_session
from canada_funeral_intel.storage.migrations import apply_pending_migrations

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "database" / "migrations"


def test_import_history_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "imports.sqlite3"

    with database_session(database_path) as connection:
        status = apply_pending_migrations(connection, MIGRATIONS).status

        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        source_record_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(source_records)")
        }

    assert status.current_version == 20
    assert "import_runs" in tables
    assert "import_run_errors" in tables
    assert "import_run_id" in source_record_columns
