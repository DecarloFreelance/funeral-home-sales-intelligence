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


def test_main_help_exposes_normalize_command() -> None:
    result = run_cli("--help")

    assert result.returncode == 0
    assert "normalize" in result.stdout


def test_normalize_help_exposes_source_filter() -> None:
    result = run_cli("normalize", "--help")

    assert result.returncode == 0
    assert "--source" in result.stdout


def test_normalize_command_runs_and_is_idempotent(tmp_path: Path) -> None:
    database_path = tmp_path / "normalize.sqlite3"
    input_path = tmp_path / "records.json"
    input_path.write_text(
        json.dumps(
            [
                {
                    "id": "001",
                    "name": "Maison funéraire Étoile Inc.",
                    "address": "Suite 205, 123 Main St SW",
                    "city": "Calgary",
                    "province": "Alberta",
                    "postal": "T2P1J9",
                    "phone": "403-555-0100",
                    "email": "INFO@EXAMPLE.CA",
                    "url": "example.ca/contact",
                    "ignored": {"nested": True},
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    env = {"DATABASE_PATH": str(database_path)}
    source = "Manual Canadian Funeral Home Source"

    imported = run_cli(
        "import",
        str(input_path),
        "--source",
        source,
        "--format",
        "json",
        "--external-id-field",
        "id",
        env=env,
    )
    first = run_cli("normalize", "--source", source, env=env)
    second = run_cli("normalize", "--source", source, env=env)

    assert imported.returncode == 0
    assert first.returncode == 0
    assert second.returncode == 0

    first_payload = json.loads(first.stdout)
    second_payload = json.loads(second.stdout)

    assert first_payload["source"] == source
    assert first_payload["records_seen"] == 1
    assert first_payload["values_inserted"] == 8
    assert first_payload["values_unchanged"] == 0
    assert first_payload["fields_skipped"] == 2

    assert second_payload["records_seen"] == 1
    assert second_payload["values_inserted"] == 0
    assert second_payload["values_unchanged"] == 8
    assert second_payload["fields_skipped"] == 2


def test_normalize_unknown_source_returns_exit_six(tmp_path: Path) -> None:
    database_path = tmp_path / "normalize.sqlite3"

    result = run_cli(
        "normalize",
        "--source",
        "Missing Source",
        env={"DATABASE_PATH": str(database_path)},
    )

    assert result.returncode == 6
    assert "normalize error: Source not found: Missing Source" in result.stderr
