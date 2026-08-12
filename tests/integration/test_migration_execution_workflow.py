from __future__ import annotations

from pathlib import Path

from canada_funeral_intel.storage import database_session
from canada_funeral_intel.storage.migrations import (
    apply_pending_migrations,
    migration_status,
)


def test_migrations_persist_across_database_sessions(tmp_path: Path) -> None:
    migration_dir = tmp_path / "migrations"
    migration_dir.mkdir()
    database_path = tmp_path / "database" / "application.sqlite3"

    (migration_dir / "0001_create_schema_migrations.sql").write_text(
        "CREATE TABLE schema_migrations ("
        "version INTEGER PRIMARY KEY, "
        "name TEXT NOT NULL, "
        "checksum TEXT NOT NULL, "
        "applied_at TEXT NOT NULL"
        ");\n",
        encoding="utf-8",
    )
    (migration_dir / "0002_create_records.sql").write_text(
        "CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT NOT NULL);\n",
        encoding="utf-8",
    )

    with database_session(database_path) as connection:
        result = apply_pending_migrations(connection, migration_dir)
        assert [migration.version for migration in result.applied] == [1, 2]

    with database_session(database_path) as connection:
        status = migration_status(connection, migration_dir)
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'records'"
        ).fetchone()

    assert status.current_version == 2
    assert len(status.applied) == 2
    assert status.pending == ()
    assert table["name"] == "records"
