from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from canada_funeral_intel.storage import database_session
from canada_funeral_intel.storage.migrations import (
    apply_pending_migrations,
    migration_status,
)

MIGRATION_DIR = Path(__file__).resolve().parents[2] / "database" / "migrations"


def migrate_database(database_path: Path) -> None:
    with database_session(database_path) as connection:
        result = apply_pending_migrations(connection, MIGRATION_DIR)
        assert result.status.current_version == 20


def insert_dataset(
    connection: sqlite3.Connection, *, name: str = "Test Directory"
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO source_datasets (
            name,
            source_type,
            source_url,
            publisher,
            jurisdiction,
            license_name,
            license_url,
            notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            name,
            "directory",
            "https://example.test/directory",
            "Example Publisher",
            "CA",
            "Open Data Licence",
            "https://example.test/licence",
            "Integration-test dataset",
        ),
    )
    connection.commit()
    assert cursor.lastrowid is not None
    return int(cursor.lastrowid)


def test_source_foundation_migrations_apply_and_are_idempotent(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "source.sqlite3"

    with database_session(database_path) as connection:
        first = apply_pending_migrations(connection, MIGRATION_DIR)
        second = apply_pending_migrations(connection, MIGRATION_DIR)

        assert [migration.version for migration in first.applied] == [
            1,
            2,
            3,
            4,
            5,
            6,
            7,
            8,
            9,
            10,
            11,
            12,
            13,
            14,
            15,
            16,
            17,
            18,
            19,
            20,
        ]
        assert second.applied == ()
        assert second.status.current_version == 20
        assert second.status.pending == ()


def test_source_foundation_tables_exist(tmp_path: Path) -> None:
    database_path = tmp_path / "source.sqlite3"
    migrate_database(database_path)

    with database_session(database_path) as connection:
        rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name IN ('source_datasets', 'source_records')
            ORDER BY name
            """
        ).fetchall()

    assert [row["name"] for row in rows] == [
        "source_datasets",
        "source_records",
    ]


def test_source_dataset_and_record_insert_with_exact_payload_round_trip(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "source.sqlite3"
    migrate_database(database_path)

    raw_payload = (
        '{"name":"Maison funéraire Étoile","phone":"403-555-0100",'
        '"nested":{"spaces":"  preserved  "}}'
    )

    with database_session(database_path) as connection:
        dataset_id = insert_dataset(connection)
        connection.execute(
            """
            INSERT INTO source_records (
                source_dataset_id,
                external_record_id,
                raw_payload,
                payload_format,
                source_url,
                retrieved_at,
                checksum
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                dataset_id,
                "record-001",
                raw_payload,
                "json",
                "https://example.test/directory/record-001",
                "2026-08-07T04:00:00Z",
                "a" * 64,
            ),
        )
        connection.commit()

        row = connection.execute(
            """
            SELECT source_dataset_id, external_record_id, raw_payload,
                   payload_format, source_url, retrieved_at, checksum
            FROM source_records
            """
        ).fetchone()

    assert row is not None
    assert row["source_dataset_id"] == dataset_id
    assert row["external_record_id"] == "record-001"
    assert row["raw_payload"] == raw_payload
    assert row["payload_format"] == "json"
    assert row["source_url"] == "https://example.test/directory/record-001"
    assert row["retrieved_at"] == "2026-08-07T04:00:00Z"
    assert row["checksum"] == "a" * 64


def test_source_record_allows_null_external_id_and_multiple_records(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "source.sqlite3"
    migrate_database(database_path)

    with database_session(database_path) as connection:
        dataset_id = insert_dataset(connection)

        for index in range(2):
            connection.execute(
                """
                INSERT INTO source_records (
                    source_dataset_id,
                    external_record_id,
                    raw_payload,
                    payload_format,
                    retrieved_at,
                    checksum
                )
                VALUES (?, NULL, ?, 'json', ?, ?)
                """,
                (
                    dataset_id,
                    f'{{"row":{index}}}',
                    f"2026-08-07T04:0{index}:00Z",
                    str(index) * 64,
                ),
            )
        connection.commit()

        rows = connection.execute(
            """
            SELECT external_record_id, raw_payload
            FROM source_records
            ORDER BY id
            """
        ).fetchall()

    assert len(rows) == 2
    assert [row["external_record_id"] for row in rows] == [None, None]
    assert [row["raw_payload"] for row in rows] == [
        '{"row":0}',
        '{"row":1}',
    ]


def test_source_record_foreign_key_is_enforced(tmp_path: Path) -> None:
    database_path = tmp_path / "source.sqlite3"
    migrate_database(database_path)

    with (
        database_session(database_path) as connection,
        pytest.raises(sqlite3.IntegrityError),
    ):
        connection.execute(
            """
                INSERT INTO source_records (
                    source_dataset_id,
                    raw_payload,
                    payload_format,
                    retrieved_at,
                    checksum
                )
                VALUES (999, '{}', 'json', '2026-08-07T04:00:00Z', ?)
                """,
            ("b" * 64,),
        )


def test_source_dataset_name_is_unique(tmp_path: Path) -> None:
    database_path = tmp_path / "source.sqlite3"
    migrate_database(database_path)

    with database_session(database_path) as connection:
        insert_dataset(connection, name="Unique Source")

        with pytest.raises(sqlite3.IntegrityError):
            insert_dataset(connection, name="Unique Source")


def test_source_dataset_delete_is_restricted_when_records_exist(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "source.sqlite3"
    migrate_database(database_path)

    with database_session(database_path) as connection:
        dataset_id = insert_dataset(connection)
        connection.execute(
            """
            INSERT INTO source_records (
                source_dataset_id,
                raw_payload,
                payload_format,
                retrieved_at,
                checksum
            )
            VALUES (?, '{}', 'json', '2026-08-07T04:00:00Z', ?)
            """,
            (dataset_id, "c" * 64),
        )
        connection.commit()

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "DELETE FROM source_datasets WHERE id = ?",
                (dataset_id,),
            )


def test_source_record_indexes_exist(tmp_path: Path) -> None:
    database_path = tmp_path / "source.sqlite3"
    migrate_database(database_path)

    with database_session(database_path) as connection:
        rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'index'
              AND tbl_name = 'source_records'
              AND name NOT LIKE 'sqlite_autoindex_%'
            ORDER BY name
            """
        ).fetchall()

    assert [row["name"] for row in rows] == [
        "idx_source_records_checksum",
        "idx_source_records_dataset",
        "idx_source_records_external_id",
        "idx_source_records_import_run",
        "idx_source_records_retrieved_at",
    ]


def test_source_provenance_survives_reopen(tmp_path: Path) -> None:
    database_path = tmp_path / "source.sqlite3"
    migrate_database(database_path)

    with database_session(database_path) as connection:
        dataset_id = insert_dataset(connection, name="Persistent Source")
        connection.execute(
            """
            INSERT INTO source_records (
                source_dataset_id,
                external_record_id,
                raw_payload,
                payload_format,
                source_url,
                retrieved_at,
                checksum
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                dataset_id,
                "persistent-001",
                "raw|payload|must|remain|exact",
                "text",
                "https://example.test/persistent-001",
                "2026-08-07T04:00:00Z",
                "d" * 64,
            ),
        )
        connection.commit()

    with database_session(database_path) as connection:
        row = connection.execute(
            """
            SELECT d.name AS dataset_name,
                   r.external_record_id,
                   r.raw_payload,
                   r.source_url
            FROM source_records AS r
            JOIN source_datasets AS d
              ON d.id = r.source_dataset_id
            """
        ).fetchone()

    assert row is not None
    assert row["dataset_name"] == "Persistent Source"
    assert row["external_record_id"] == "persistent-001"
    assert row["raw_payload"] == "raw|payload|must|remain|exact"
    assert row["source_url"] == "https://example.test/persistent-001"


def test_migration_status_reports_version_two(tmp_path: Path) -> None:
    database_path = tmp_path / "source.sqlite3"
    migrate_database(database_path)

    with database_session(database_path) as connection:
        status = migration_status(connection, MIGRATION_DIR)

    assert status.current_version == 20
    assert [migration.version for migration in status.applied] == [
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        8,
        9,
        10,
        11,
        12,
        13,
        14,
        15,
        16,
        17,
        18,
        19,
        20,
    ]
    assert status.pending == ()
    assert status.consistent is True
