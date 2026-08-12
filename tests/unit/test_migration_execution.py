from __future__ import annotations

from pathlib import Path

import pytest

from canada_funeral_intel.storage import connect_database
from canada_funeral_intel.storage.migrations import (
    MigrationError,
    apply_pending_migrations,
    list_applied_migrations,
    migration_status,
)


def write_migration(directory: Path, name: str, sql: str) -> Path:
    path = directory / name
    path.write_text(sql, encoding="utf-8")
    return path


def bootstrap_sql() -> str:
    return (
        "CREATE TABLE schema_migrations ("
        "version INTEGER PRIMARY KEY, "
        "name TEXT NOT NULL, "
        "checksum TEXT NOT NULL, "
        "applied_at TEXT NOT NULL"
        ");\n"
    )


def test_status_before_bootstrap_lists_all_as_pending(tmp_path: Path) -> None:
    write_migration(
        tmp_path,
        "0001_create_schema_migrations.sql",
        bootstrap_sql(),
    )
    connection = connect_database(tmp_path / "db" / "test.sqlite3")
    try:
        status = migration_status(connection, tmp_path)
    finally:
        connection.close()

    assert status.current_version == 0
    assert status.applied == ()
    assert [migration.version for migration in status.pending] == [1]


def test_apply_bootstrap_records_complete_history(tmp_path: Path) -> None:
    write_migration(
        tmp_path,
        "0001_create_schema_migrations.sql",
        bootstrap_sql(),
    )
    connection = connect_database(tmp_path / "db" / "test.sqlite3")
    try:
        result = apply_pending_migrations(connection, tmp_path)
        records = list_applied_migrations(connection)
    finally:
        connection.close()

    assert [migration.version for migration in result.applied] == [1]
    assert len(records) == 1
    assert records[0].name == "0001_create_schema_migrations.sql"
    assert len(records[0].checksum) == 64
    assert records[0].applied_at.endswith("+00:00")


def test_apply_multiple_migrations_in_order(tmp_path: Path) -> None:
    write_migration(
        tmp_path,
        "0001_create_schema_migrations.sql",
        bootstrap_sql(),
    )
    write_migration(
        tmp_path,
        "0002_create_example.sql",
        "CREATE TABLE example (id INTEGER PRIMARY KEY);\n",
    )
    write_migration(
        tmp_path,
        "0003_add_name.sql",
        "ALTER TABLE example ADD COLUMN name TEXT;\n",
    )

    connection = connect_database(tmp_path / "db" / "test.sqlite3")
    try:
        result = apply_pending_migrations(connection, tmp_path)
        columns = [
            row["name"] for row in connection.execute("PRAGMA table_info(example)")
        ]
    finally:
        connection.close()

    assert [migration.version for migration in result.applied] == [1, 2, 3]
    assert columns == ["id", "name"]
    assert result.status.current_version == 3
    assert result.status.pending == ()


def test_repeated_execution_is_idempotent(tmp_path: Path) -> None:
    write_migration(
        tmp_path,
        "0001_create_schema_migrations.sql",
        bootstrap_sql(),
    )
    connection = connect_database(tmp_path / "db" / "test.sqlite3")
    try:
        first = apply_pending_migrations(connection, tmp_path)
        second = apply_pending_migrations(connection, tmp_path)
        records = list_applied_migrations(connection)
    finally:
        connection.close()

    assert len(first.applied) == 1
    assert second.applied == ()
    assert len(records) == 1


def test_changed_applied_migration_is_rejected(tmp_path: Path) -> None:
    migration = write_migration(
        tmp_path,
        "0001_create_schema_migrations.sql",
        bootstrap_sql(),
    )
    connection = connect_database(tmp_path / "db" / "test.sqlite3")
    try:
        apply_pending_migrations(connection, tmp_path)
        migration.write_text(bootstrap_sql() + "-- changed\n", encoding="utf-8")

        with pytest.raises(MigrationError, match="checksum changed"):
            migration_status(connection, tmp_path)
    finally:
        connection.close()


def test_failed_migration_rolls_back_schema_and_history(tmp_path: Path) -> None:
    write_migration(
        tmp_path,
        "0001_create_schema_migrations.sql",
        bootstrap_sql(),
    )
    write_migration(
        tmp_path,
        "0002_broken.sql",
        "CREATE TABLE should_rollback (id INTEGER PRIMARY KEY);\n"
        "INSERT INTO missing_table (id) VALUES (1);\n",
    )

    connection = connect_database(tmp_path / "db" / "test.sqlite3")
    try:
        with pytest.raises(MigrationError, match="0002_broken.sql"):
            apply_pending_migrations(connection, tmp_path)

        table = connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name = 'should_rollback'"
        ).fetchone()
        versions = [
            row["version"]
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]
    finally:
        connection.close()

    assert table is None
    assert versions == [1]


def test_failed_bootstrap_rolls_back_partial_schema(tmp_path: Path) -> None:
    write_migration(
        tmp_path,
        "0001_broken_bootstrap.sql",
        bootstrap_sql() + "INSERT INTO missing_table (id) VALUES (1);\n",
    )
    connection = connect_database(tmp_path / "db" / "test.sqlite3")
    try:
        with pytest.raises(MigrationError, match="0001_broken_bootstrap.sql"):
            apply_pending_migrations(connection, tmp_path)

        assert list_applied_migrations(connection) == []
        table = connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name = 'schema_migrations'"
        ).fetchone()
    finally:
        connection.close()

    assert table is None


def test_incomplete_sql_is_rejected(tmp_path: Path) -> None:
    write_migration(
        tmp_path,
        "0001_create_schema_migrations.sql",
        "CREATE TABLE schema_migrations (",
    )
    connection = connect_database(tmp_path / "db" / "test.sqlite3")
    try:
        with pytest.raises(MigrationError, match="incomplete SQL"):
            apply_pending_migrations(connection, tmp_path)
    finally:
        connection.close()


def test_transaction_control_is_rejected(tmp_path: Path) -> None:
    write_migration(
        tmp_path,
        "0001_create_schema_migrations.sql",
        "BEGIN;\n",
    )
    connection = connect_database(tmp_path / "db" / "test.sqlite3")
    try:
        with pytest.raises(MigrationError, match="transaction-control"):
            apply_pending_migrations(connection, tmp_path)
    finally:
        connection.close()


def test_unexpected_tracking_schema_is_rejected(tmp_path: Path) -> None:
    connection = connect_database(tmp_path / "db" / "test.sqlite3")
    try:
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY)"
        )
        with pytest.raises(MigrationError, match="unexpected schema"):
            list_applied_migrations(connection)
    finally:
        connection.close()
