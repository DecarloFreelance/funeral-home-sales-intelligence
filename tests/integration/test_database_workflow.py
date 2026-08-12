from __future__ import annotations

from pathlib import Path

from canada_funeral_intel.storage import database_session, transaction


def test_database_workflow_persists_committed_data(tmp_path: Path) -> None:
    database_path = tmp_path / "workflow.sqlite3"

    with database_session(database_path) as connection:
        connection.execute(
            "CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
        )
        with transaction(connection):
            connection.execute(
                "INSERT INTO records (value) VALUES (?)",
                ("persisted",),
            )

    with database_session(database_path) as connection:
        row = connection.execute("SELECT value FROM records").fetchone()

    assert row["value"] == "persisted"
