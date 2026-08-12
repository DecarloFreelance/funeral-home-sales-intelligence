from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from canada_funeral_intel.storage import (
    DatabaseError,
    connect_database,
    database_session,
    transaction,
)


def test_connection_creates_parent_directories(tmp_path: Path) -> None:
    database_path = tmp_path / "nested" / "db" / "test.sqlite3"

    connection = connect_database(database_path)
    connection.close()

    assert database_path.is_file()


def test_connection_uses_rows_and_foreign_keys(tmp_path: Path) -> None:
    connection = connect_database(tmp_path / "test.sqlite3")
    try:
        assert connection.row_factory is sqlite3.Row
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    finally:
        connection.close()


def test_transaction_commits(tmp_path: Path) -> None:
    connection = connect_database(tmp_path / "test.sqlite3")
    try:
        connection.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
        with transaction(connection):
            connection.execute("INSERT INTO items (name) VALUES (?)", ("committed",))

        row = connection.execute("SELECT name FROM items").fetchone()
        assert row["name"] == "committed"
    finally:
        connection.close()


def test_transaction_rolls_back(tmp_path: Path) -> None:
    connection = connect_database(tmp_path / "test.sqlite3")
    try:
        connection.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")

        with (
            pytest.raises(
                RuntimeError,
                match="force rollback",
            ),
            transaction(connection),
        ):
            connection.execute(
                "INSERT INTO items (name) VALUES (?)",
                ("rolled back",),
            )
            raise RuntimeError("force rollback")

        count = connection.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        assert count == 0
    finally:
        connection.close()


def test_foreign_key_violation_is_enforced(tmp_path: Path) -> None:
    connection = connect_database(tmp_path / "test.sqlite3")
    try:
        connection.executescript(
            """
            CREATE TABLE parents (
                id INTEGER PRIMARY KEY
            );
            CREATE TABLE children (
                id INTEGER PRIMARY KEY,
                parent_id INTEGER NOT NULL REFERENCES parents(id)
            );
            """
        )

        with (
            pytest.raises(
                sqlite3.IntegrityError,
            ),
            transaction(connection),
        ):
            connection.execute(
                "INSERT INTO children (parent_id) VALUES (?)",
                (999,),
            )
    finally:
        connection.close()


def test_nested_transactions_are_rejected(tmp_path: Path) -> None:
    connection = connect_database(tmp_path / "test.sqlite3")
    try:
        with (
            transaction(connection),
            pytest.raises(
                DatabaseError,
                match="Nested transactions",
            ),
            transaction(connection),
        ):
            pass
    finally:
        connection.close()


def test_database_session_closes_connection(tmp_path: Path) -> None:
    connection: sqlite3.Connection

    with database_session(tmp_path / "test.sqlite3") as connection:
        connection.execute("SELECT 1")

    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")
