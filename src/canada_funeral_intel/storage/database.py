from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class DatabaseError(RuntimeError):
    """Raised when a database operation cannot be completed safely."""


def connect_database(path: Path | str) -> sqlite3.Connection:
    """Open a configured SQLite connection with safe defaults."""
    database_path = Path(path).expanduser()

    if database_path != Path(":memory:"):
        database_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        connection = sqlite3.connect(database_path)
    except sqlite3.Error as exc:
        raise DatabaseError(
            f"Unable to open SQLite database at {database_path}: {exc}"
        ) from exc

    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")

    enabled = connection.execute("PRAGMA foreign_keys").fetchone()
    if enabled is None or enabled[0] != 1:
        connection.close()
        raise DatabaseError("SQLite foreign-key enforcement could not be enabled")

    return connection


@contextmanager
def transaction(connection: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run operations atomically, committing or rolling back as needed."""
    if connection.in_transaction:
        raise DatabaseError("Nested transactions are not supported")

    try:
        connection.execute("BEGIN")
        yield connection
    except BaseException:
        connection.rollback()
        raise
    else:
        connection.commit()


@contextmanager
def database_session(path: Path | str) -> Iterator[sqlite3.Connection]:
    """Open a connection for a bounded unit of work and always close it."""
    connection = connect_database(path)
    try:
        yield connection
    finally:
        connection.close()
