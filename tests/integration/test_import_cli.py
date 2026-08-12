from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def run_cli(
    *args: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    command_env = os.environ.copy()
    if env:
        command_env.update(env)
    return subprocess.run(
        [sys.executable, "-m", "canada_funeral_intel", *args],
        check=False,
        capture_output=True,
        text=True,
        env=command_env,
    )


def test_import_json_and_repeat_is_unchanged(tmp_path: Path) -> None:
    database_path = tmp_path / "import.sqlite3"
    input_path = tmp_path / "records.json"
    input_path.write_text(
        '[{"id":"1","name":"Alpha"},{"id":"2","name":"Beta"}]',
        encoding="utf-8",
    )
    env = {"DATABASE_PATH": str(database_path)}
    args = (
        "import",
        str(input_path),
        "--source",
        "Manual Canadian Funeral Home Source",
        "--format",
        "json",
        "--external-id-field",
        "id",
    )

    first = run_cli(*args, env=env)
    second = run_cli(*args, env=env)

    assert first.returncode == 0
    assert second.returncode == 0

    first_payload = json.loads(first.stdout)
    second_payload = json.loads(second.stdout)

    assert first_payload["records_seen"] == 2
    assert first_payload["records_inserted"] == 2
    assert first_payload["records_unchanged"] == 0
    assert first_payload["records_failed"] == 0

    assert second_payload["records_seen"] == 2
    assert second_payload["records_inserted"] == 0
    assert second_payload["records_unchanged"] == 2
    assert second_payload["records_failed"] == 0


def test_import_csv(tmp_path: Path) -> None:
    database_path = tmp_path / "import.sqlite3"
    input_path = tmp_path / "records.csv"
    input_path.write_text(
        "id,name\n1,Alpha\n2,Beta\n",
        encoding="utf-8",
    )

    result = run_cli(
        "import",
        str(input_path),
        "--source",
        "Manual Canadian Funeral Home Source",
        "--format",
        "csv",
        "--external-id-field",
        "id",
        env={"DATABASE_PATH": str(database_path)},
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["input_format"] == "csv"
    assert payload["records_seen"] == 2
    assert payload["records_inserted"] == 2


def test_import_persists_row_errors_and_returns_success(tmp_path: Path) -> None:
    database_path = tmp_path / "import.sqlite3"
    input_path = tmp_path / "records.json"
    input_path.write_text(
        '[{"id":"ok","name":"Alpha"},42]',
        encoding="utf-8",
    )

    result = run_cli(
        "import",
        str(input_path),
        "--source",
        "Manual Canadian Funeral Home Source",
        "--format",
        "json",
        "--external-id-field",
        "id",
        env={"DATABASE_PATH": str(database_path)},
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["records_seen"] == 2
    assert payload["records_inserted"] == 1
    assert payload["records_failed"] == 1


def test_import_unknown_source_returns_exit_five(tmp_path: Path) -> None:
    input_path = tmp_path / "records.json"
    input_path.write_text("[]", encoding="utf-8")

    result = run_cli(
        "import",
        str(input_path),
        "--source",
        "Missing Source",
        "--format",
        "json",
        env={"DATABASE_PATH": str(tmp_path / "import.sqlite3")},
    )

    assert result.returncode == 5
    assert "import error" in result.stderr
    assert "Source not found" in result.stderr


def test_import_help_is_available() -> None:
    result = run_cli("import", "--help")

    assert result.returncode == 0
    assert "--source" in result.stdout
    assert "--format" in result.stdout
    assert "--external-id-field" in result.stdout
