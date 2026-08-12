from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _run_cli(
    *args: str,
    database_path: Path,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["DATABASE_PATH"] = str(database_path)

    return subprocess.run(
        [
            sys.executable,
            "-m",
            "canada_funeral_intel",
            *args,
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def _seed_database(
    database_path: Path,
) -> None:
    connection = sqlite3.connect(database_path)

    connection.executescript(
        """
        CREATE TABLE source_records (
            id INTEGER PRIMARY KEY
        );

        CREATE TABLE normalized_values (
            id INTEGER PRIMARY KEY,
            source_record_id INTEGER NOT NULL,
            field_name TEXT NOT NULL,
            normalized_value TEXT
        );

        CREATE TABLE entities (
            id INTEGER PRIMARY KEY,
            entity_type TEXT NOT NULL
                CHECK (
                    entity_type IN (
                        'organization',
                        'branch'
                    )
                ),
            canonical_name TEXT,
            parent_entity_id INTEGER,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (
                    status IN (
                        'active',
                        'merged',
                        'inactive'
                    )
                ),
            created_at TEXT NOT NULL DEFAULT (
                strftime(
                    '%Y-%m-%dT%H:%M:%fZ',
                    'now'
                )
            ),
            updated_at TEXT NOT NULL DEFAULT (
                strftime(
                    '%Y-%m-%dT%H:%M:%fZ',
                    'now'
                )
            )
        );

        CREATE TABLE entity_source_records (
            entity_id INTEGER NOT NULL,
            source_record_id INTEGER NOT NULL,
            membership_role TEXT NOT NULL
                DEFAULT 'location'
                CHECK (
                    membership_role IN (
                        'organization',
                        'location',
                        'branch'
                    )
                ),
            created_at TEXT NOT NULL DEFAULT (
                strftime(
                    '%Y-%m-%dT%H:%M:%fZ',
                    'now'
                )
            ),
            PRIMARY KEY (
                entity_id,
                source_record_id
            )
        );
        """
    )

    connection.executemany(
        """
        INSERT INTO source_records (id)
        VALUES (?)
        """,
        (
            (1,),
            (2,),
            (3,),
        ),
    )

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
            (
                1,
                "business_name",
                "old funeral home",
            ),
            (
                1,
                "business_name",
                "new funeral home",
            ),
            (
                2,
                "business_name",
                "second funeral home",
            ),
            (
                3,
                "business_name",
                "obsolete name",
            ),
            (
                3,
                "business_name",
                None,
            ),
        ),
    )

    connection.commit()
    connection.close()


def test_entity_materialize_cli_is_idempotent(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "entity-materialize.sqlite3"

    _seed_database(database_path)

    first = _run_cli(
        "entity",
        "materialize",
        database_path=database_path,
    )

    second = _run_cli(
        "entity",
        "materialize",
        database_path=database_path,
    )

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr

    assert json.loads(first.stdout) == {
        "entities_inserted": 3,
        "memberships_inserted": 3,
        "records_unchanged": 0,
        "source_records_seen": 3,
    }

    assert json.loads(second.stdout) == {
        "entities_inserted": 0,
        "memberships_inserted": 0,
        "records_unchanged": 3,
        "source_records_seen": 3,
    }


def test_entity_materialize_uses_latest_name_semantics(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "latest-name.sqlite3"

    _seed_database(database_path)

    result = _run_cli(
        "entity",
        "materialize",
        database_path=database_path,
    )

    assert result.returncode == 0, result.stderr

    connection = sqlite3.connect(database_path)

    rows = connection.execute(
        """
        SELECT
            esr.source_record_id,
            e.entity_type,
            e.canonical_name,
            esr.membership_role
        FROM entity_source_records AS esr
        JOIN entities AS e
          ON e.id = esr.entity_id
        ORDER BY esr.source_record_id
        """
    ).fetchall()

    connection.close()

    assert rows == [
        (
            1,
            "branch",
            "new funeral home",
            "location",
        ),
        (
            2,
            "branch",
            "second funeral home",
            "location",
        ),
        (
            3,
            "branch",
            None,
            "location",
        ),
    ]


def test_existing_membership_is_not_duplicated(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "existing.sqlite3"

    _seed_database(database_path)

    connection = sqlite3.connect(database_path)

    entity_id = connection.execute(
        """
        INSERT INTO entities (
            entity_type,
            canonical_name,
            status
        )
        VALUES (
            'branch',
            'already exists',
            'active'
        )
        """
    ).lastrowid

    assert entity_id is not None

    connection.execute(
        """
        INSERT INTO entity_source_records (
            entity_id,
            source_record_id,
            membership_role
        )
        VALUES (?, 1, 'location')
        """,
        (entity_id,),
    )

    connection.commit()
    connection.close()

    result = _run_cli(
        "entity",
        "materialize",
        database_path=database_path,
    )

    assert result.returncode == 0, result.stderr

    payload = json.loads(result.stdout)

    assert payload == {
        "entities_inserted": 2,
        "memberships_inserted": 2,
        "records_unchanged": 1,
        "source_records_seen": 3,
    }

    connection = sqlite3.connect(database_path)

    entity_count = connection.execute("SELECT COUNT(*) FROM entities").fetchone()[0]

    membership_count = connection.execute(
        """
        SELECT COUNT(*)
        FROM entity_source_records
        """
    ).fetchone()[0]

    connection.close()

    assert entity_count == 3
    assert membership_count == 3


def test_entity_materialize_database_error_exit_code(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "invalid.sqlite3"

    sqlite3.connect(database_path).close()

    result = _run_cli(
        "entity",
        "materialize",
        database_path=database_path,
    )

    assert result.returncode == 11
    assert "entity error:" in result.stderr
