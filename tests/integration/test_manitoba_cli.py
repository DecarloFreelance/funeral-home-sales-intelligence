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


def test_sources_collect_help_is_available() -> None:
    result = run_cli("sources", "collect", "--help")

    assert result.returncode == 0
    assert "Funeral Board of Manitoba" in " ".join(result.stdout.split())
    assert "--timeout" in result.stdout


def test_manitoba_source_is_registered() -> None:
    result = run_cli("sources", "show", "Funeral Board of Manitoba")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["source_format"] == "pdf"
    assert payload["source_type"] == "regulator"
    assert payload["trust_level"] == "authoritative"
    assert payload["jurisdiction"] == "MB"
    assert payload["coverage"] == ["MB"]


def test_unknown_live_source_returns_exit_five(tmp_path: Path) -> None:
    result = run_cli(
        "sources",
        "collect",
        "Manual Canadian Funeral Home Source",
        env={"DATABASE_PATH": str(tmp_path / "collect.sqlite3")},
    )

    assert result.returncode == 5
    assert "collection error" in result.stderr
