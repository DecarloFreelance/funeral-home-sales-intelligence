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


def _seed_matching_database(
    database_path: Path,
) -> None:
    connection = sqlite3.connect(database_path)

    connection.executescript(
        """
        CREATE TABLE normalized_values (
            id INTEGER PRIMARY KEY,
            source_record_id INTEGER NOT NULL,
            field_name TEXT NOT NULL,
            normalized_value TEXT
        );

        CREATE TABLE match_candidates (
            id INTEGER PRIMARY KEY,
            left_source_record_id INTEGER NOT NULL,
            right_source_record_id INTEGER NOT NULL,
            candidate_method TEXT NOT NULL,
            score REAL NOT NULL,
            decision TEXT NOT NULL,
            created_at TEXT,
            updated_at TEXT
        );

        CREATE TABLE match_evidence (
            id INTEGER PRIMARY KEY,
            match_candidate_id INTEGER NOT NULL,
            signal_name TEXT NOT NULL,
            left_value TEXT,
            right_value TEXT,
            contribution REAL NOT NULL,
            evidence_kind TEXT NOT NULL,
            created_at TEXT
        );
        """
    )

    values = (
        (1, "business_name", "voyage funeral home crematorium"),
        (1, "city", "Winnipeg"),
        (1, "province", "MB"),
        (1, "phone", "+12046683151"),
        (2, "business_name", "voyage funeral home crematorium"),
        (2, "city", "Winnipeg"),
        (2, "province", "MB"),
        (2, "phone", "+12046683151"),
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
        values,
    )

    connection.commit()
    connection.close()


def test_match_deterministic_cli_is_idempotent(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "deterministic.sqlite3"
    _seed_matching_database(database_path)

    first = _run_cli(
        "match",
        "deterministic",
        database_path=database_path,
    )
    second = _run_cli(
        "match",
        "deterministic",
        database_path=database_path,
    )

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr

    first_payload = json.loads(first.stdout)
    second_payload = json.loads(second.stdout)

    assert first_payload == {
        "deterministic": {
            "candidates_inserted": 1,
            "candidates_unchanged": 0,
            "evidence_inserted": 4,
            "pairs_found": 1,
            "records_seen": 2,
        },
        "mode": "deterministic",
    }

    assert second_payload == {
        "deterministic": {
            "candidates_inserted": 0,
            "candidates_unchanged": 1,
            "evidence_inserted": 0,
            "pairs_found": 1,
            "records_seen": 2,
        },
        "mode": "deterministic",
    }


def test_match_fuzzy_cli_is_idempotent(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "fuzzy.sqlite3"
    _seed_matching_database(database_path)

    first = _run_cli(
        "match",
        "fuzzy",
        database_path=database_path,
    )
    second = _run_cli(
        "match",
        "fuzzy",
        database_path=database_path,
    )

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr

    first_payload = json.loads(first.stdout)
    second_payload = json.loads(second.stdout)

    assert first_payload["mode"] == "fuzzy"
    assert first_payload["fuzzy"]["records_seen"] == 2
    assert first_payload["fuzzy"]["blocked_pairs"] == 1
    assert first_payload["fuzzy"]["pairs_scored"] == 1
    assert first_payload["fuzzy"]["candidates_inserted"] == 1
    assert first_payload["fuzzy"]["candidates_unchanged"] == 0
    assert first_payload["fuzzy"]["evidence_inserted"] == 3

    assert second_payload["fuzzy"] == {
        "blocked_pairs": 1,
        "candidates_inserted": 0,
        "candidates_unchanged": 1,
        "evidence_inserted": 0,
        "pairs_scored": 1,
        "records_seen": 2,
    }


def test_match_all_cli_runs_both_matchers(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "all.sqlite3"
    _seed_matching_database(database_path)

    result = _run_cli(
        "match",
        "all",
        database_path=database_path,
    )

    assert result.returncode == 0, result.stderr

    payload = json.loads(result.stdout)

    assert payload["mode"] == "all"
    assert payload["deterministic"]["candidates_inserted"] == 1
    assert payload["fuzzy"]["candidates_inserted"] == 1

    connection = sqlite3.connect(database_path)

    methods = dict(
        connection.execute(
            """
            SELECT
                candidate_method,
                COUNT(*)
            FROM match_candidates
            GROUP BY candidate_method
            ORDER BY candidate_method
            """
        ).fetchall()
    )

    evidence_count = connection.execute(
        """
        SELECT COUNT(*)
        FROM match_evidence
        """
    ).fetchone()[0]

    connection.close()

    assert methods == {
        "deterministic_v1": 1,
        "fuzzy_weighted_v1": 1,
    }

    assert evidence_count == 7


def test_match_cli_database_failure_has_dedicated_exit_code(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "invalid.sqlite3"
    sqlite3.connect(database_path).close()

    result = _run_cli(
        "match",
        "deterministic",
        database_path=database_path,
    )

    assert result.returncode == 10
    assert "match error:" in result.stderr
