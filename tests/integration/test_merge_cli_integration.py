from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path


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


def _seed(database_path: Path) -> tuple[int, int]:
    assert _run_cli("db", "init", database_path=database_path).returncode == 0
    with sqlite3.connect(database_path) as connection:
        survivor = connection.execute(
            "INSERT INTO entities (entity_type, canonical_name) VALUES ('organization', 'Survivor')"
        ).lastrowid
        merged = connection.execute(
            "INSERT INTO entities (entity_type, canonical_name) VALUES ('organization', 'Merged')"
        ).lastrowid
        assert survivor is not None and merged is not None
        connection.commit()
        return int(survivor), int(merged)


def test_merge_cli_apply_and_rollback(tmp_path: Path) -> None:
    database_path = tmp_path / "merge-cli.sqlite3"
    survivor, merged = _seed(database_path)
    applied = _run_cli(
        "merge",
        "apply",
        str(survivor),
        str(merged),
        "--source",
        "manual_review",
        "--reason",
        "same organization confirmed",
        database_path=database_path,
    )
    assert applied.returncode == 0
    payload = json.loads(applied.stdout)
    assert payload["survivor_entity_id"] == survivor
    assert payload["merged_entity_id"] == merged
    rolled_back = _run_cli(
        "merge",
        "rollback",
        str(payload["merge_history_id"]),
        database_path=database_path,
    )
    assert rolled_back.returncode == 0
    assert json.loads(rolled_back.stdout)["restored_entity_id"] == merged


def test_merge_cli_missing_entity_returns_exit_eight(tmp_path: Path) -> None:
    database_path = tmp_path / "merge-cli.sqlite3"
    _seed(database_path)
    result = _run_cli(
        "merge",
        "apply",
        "1",
        "999",
        "--source",
        "manual",
        "--reason",
        "fixture",
        database_path=database_path,
    )
    assert result.returncode == 8
    assert "merge error" in result.stderr
