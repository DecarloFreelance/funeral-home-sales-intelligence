from __future__ import annotations

import sqlite3

from canada_funeral_intel.deduplication import deterministic, fuzzy


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE normalized_values (
            id INTEGER PRIMARY KEY,
            source_record_id INTEGER NOT NULL,
            field_name TEXT NOT NULL,
            normalized_value TEXT
        )
        """
    )
    return connection


def _loaders():
    return (
        deterministic._load_latest_normalized_signals,
        fuzzy._load_latest_normalized_signals,
    )


def test_latest_null_invalidates_older_non_null_signal() -> None:
    connection = _connection()

    connection.execute(
        """
        INSERT INTO normalized_values (
            source_record_id,
            field_name,
            normalized_value
        )
        VALUES (?, ?, ?)
        """,
        (1, "phone", "+12049827550 x1"),
    )
    connection.execute(
        """
        INSERT INTO normalized_values (
            source_record_id,
            field_name,
            normalized_value
        )
        VALUES (?, ?, ?)
        """,
        (1, "phone", None),
    )

    for loader in _loaders():
        signals = loader(connection)

        assert signals.get(1, {}).get("phone") is None


def test_latest_non_null_signal_remains_available() -> None:
    connection = _connection()

    connection.execute(
        """
        INSERT INTO normalized_values (
            source_record_id,
            field_name,
            normalized_value
        )
        VALUES (?, ?, ?)
        """,
        (1, "phone", None),
    )
    connection.execute(
        """
        INSERT INTO normalized_values (
            source_record_id,
            field_name,
            normalized_value
        )
        VALUES (?, ?, ?)
        """,
        (1, "phone", "+12049827550 x1"),
    )

    for loader in _loaders():
        signals = loader(connection)

        assert signals[1]["phone"] == "+12049827550 x1"


def test_latest_selection_is_independent_per_field() -> None:
    connection = _connection()

    connection.executemany(
        """
        INSERT INTO normalized_values (
            source_record_id,
            field_name,
            normalized_value
        )
        VALUES (?, ?, ?)
        """,
        (
            (1, "phone", "+12049827550 x1"),
            (1, "business_name", "glen lawn funeral home"),
            (1, "phone", None),
            (1, "city", "Winnipeg"),
        ),
    )

    for loader in _loaders():
        signals = loader(connection)

        assert signals[1] == {
            "business_name": "glen lawn funeral home",
            "city": "Winnipeg",
        }
