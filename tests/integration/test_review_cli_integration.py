from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from canada_funeral_intel.storage import database_session
from canada_funeral_intel.storage.migrations import apply_pending_migrations

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "database" / "migrations"


def _run_cli(*args: str, database_path: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["DATABASE_PATH"] = str(database_path)
    return subprocess.run(
        [sys.executable, "-m", "canada_funeral_intel", *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _seed_review_candidate(database_path: Path) -> int:
    with database_session(database_path) as connection:
        result = apply_pending_migrations(connection, MIGRATIONS)
        assert result.status.current_version == 15
        connection.execute(
            """
            INSERT INTO source_datasets (id, name, source_type, jurisdiction, is_active)
            VALUES (1, 'Fixture Source', 'manual', 'AB', 1)
            """
        )
        source_ids = []
        for external_id in ("left", "right"):
            cursor = connection.execute(
                """
                INSERT INTO source_records (
                    source_dataset_id, external_record_id, raw_payload, payload_format,
                    source_url, retrieved_at, checksum
                )
                VALUES (
                    1, ?, '{}', 'json', 'https://example.test/record',
                    '2026-08-08T00:00:00+00:00', ?
                )
                """,
                (external_id, f"checksum-{external_id}"),
            )
            assert cursor.lastrowid is not None
            source_ids.append(int(cursor.lastrowid))
        cursor = connection.execute(
            """
            INSERT INTO match_candidates (
                left_source_record_id, right_source_record_id,
                candidate_method, score, decision
            )
            VALUES (?, ?, 'fixture_review', 0.90, 'review')
            """,
            tuple(source_ids),
        )
        assert cursor.lastrowid is not None
        connection.commit()
        return int(cursor.lastrowid)


def test_review_cli_populate_list_and_approve(tmp_path: Path) -> None:
    database_path = tmp_path / "review-cli.sqlite3"
    candidate_id = _seed_review_candidate(database_path)

    populated = _run_cli("review", "populate", database_path=database_path)
    assert populated.returncode == 0
    assert json.loads(populated.stdout)["queue_entries_inserted"] == 1

    listed = _run_cli("review", "list", database_path=database_path)
    assert listed.returncode == 0
    list_payload = json.loads(listed.stdout)
    assert len(list_payload) == 1
    queue_id = list_payload[0]["queue_id"]
    assert list_payload[0]["match_candidate_id"] == candidate_id

    decided = _run_cli(
        "review",
        "decide",
        str(queue_id),
        "--decision",
        "approved",
        "--note",
        "confirmed manually",
        database_path=database_path,
    )
    assert decided.returncode == 0
    decision_payload = json.loads(decided.stdout)
    assert decision_payload["candidate_decision"] == "match"
    assert decision_payload["review_status"] == "approved"

    with sqlite3.connect(database_path) as connection:
        decision = connection.execute(
            "SELECT decision FROM match_candidates WHERE id = ?", (candidate_id,)
        ).fetchone()[0]
    assert decision == "match"


def test_review_cli_can_list_all_statuses(tmp_path: Path) -> None:
    database_path = tmp_path / "review-cli.sqlite3"
    _seed_review_candidate(database_path)
    assert _run_cli("review", "populate", database_path=database_path).returncode == 0
    listed = _run_cli("review", "list", "--status", "all", database_path=database_path)
    assert listed.returncode == 0
    assert len(json.loads(listed.stdout)) == 1


def test_review_cli_missing_entry_returns_exit_seven(tmp_path: Path) -> None:
    database_path = tmp_path / "review-cli.sqlite3"
    _seed_review_candidate(database_path)
    result = _run_cli(
        "review",
        "decide",
        "999",
        "--decision",
        "approved",
        database_path=database_path,
    )
    assert result.returncode == 7
    assert "review error" in result.stderr
    assert "not found" in result.stderr
