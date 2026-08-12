from __future__ import annotations

import json
import os
import sqlite3
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


def test_cli_help() -> None:
    result = run_cli("--help")
    assert result.returncode == 0
    assert "Canada Funeral Intelligence" in result.stdout
    assert "config" in result.stdout
    assert "db" in result.stdout


def test_config_show() -> None:
    result = run_cli(
        "config",
        "show",
        env={
            "DATABASE_PATH": "/tmp/test.sqlite3",
            "LOG_LEVEL": "WARNING",
        },
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["database_path"] == "/tmp/test.sqlite3"
    assert payload["log_level"] == "WARNING"


def test_invalid_configuration_returns_exit_two() -> None:
    result = run_cli(
        "config",
        "show",
        env={"MAX_CONCURRENCY": "0"},
    )
    assert result.returncode == 2
    assert "configuration error" in result.stderr


def test_db_status_before_migration(tmp_path: Path) -> None:
    database_path = tmp_path / "nested" / "status.sqlite3"
    result = run_cli(
        "db",
        "status",
        env={"DATABASE_PATH": str(database_path)},
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["database_path"] == str(database_path)
    assert payload["database_exists"] is False
    assert payload["discovered_migrations"] == 22
    assert payload["applied_migrations"] == 0
    assert payload["pending_migrations"] == 22
    assert payload["current_version"] == 0
    assert payload["consistent"] is True


def test_db_init_applies_migration_and_is_idempotent(tmp_path: Path) -> None:
    database_path = tmp_path / "nested" / "init.sqlite3"
    env = {"DATABASE_PATH": str(database_path)}

    first = run_cli("db", "init", env=env)
    second = run_cli("db", "init", env=env)

    assert first.returncode == 0
    assert second.returncode == 0
    assert database_path.is_file()

    first_payload = json.loads(first.stdout)
    second_payload = json.loads(second.stdout)

    assert first_payload["applied_migrations"] == 22
    assert first_payload["current_version"] == 22
    assert second_payload["applied_migrations"] == 0
    assert second_payload["current_version"] == 22


def test_db_migrate_applies_pending_then_noops(tmp_path: Path) -> None:
    database_path = tmp_path / "migrate.sqlite3"
    env = {"DATABASE_PATH": str(database_path)}

    first = run_cli("db", "migrate", env=env)
    second = run_cli("db", "migrate", env=env)

    assert first.returncode == 0
    assert second.returncode == 0
    assert json.loads(first.stdout)["applied_migrations"] == 22
    assert json.loads(second.stdout)["applied_migrations"] == 0


def test_db_status_after_migration(tmp_path: Path) -> None:
    database_path = tmp_path / "status.sqlite3"
    env = {"DATABASE_PATH": str(database_path)}

    migrated = run_cli("db", "migrate", env=env)
    status = run_cli("db", "status", env=env)

    assert migrated.returncode == 0
    assert status.returncode == 0

    payload = json.loads(status.stdout)
    assert payload["database_exists"] is True
    assert payload["discovered_migrations"] == 22
    assert payload["applied_migrations"] == 22
    assert payload["pending_migrations"] == 0
    assert payload["current_version"] == 22
    assert payload["consistent"] is True


def test_sources_validate() -> None:
    result = run_cli("sources", "validate")

    assert result.returncode == 0

    payload = json.loads(result.stdout)
    assert payload["valid"] is True
    assert payload["count"] == 4
    assert payload["registry_path"].endswith("config/sources.json")


def test_sources_seed_initializes_registry_and_is_idempotent(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sources-seed.sqlite3"
    env = {"DATABASE_PATH": str(database_path)}

    first = run_cli("sources", "seed", env=env)
    second = run_cli("sources", "seed", env=env)

    assert first.returncode == 0
    assert second.returncode == 0

    first_payload = json.loads(first.stdout)
    second_payload = json.loads(second.stdout)

    assert first_payload["database_path"] == str(database_path)
    assert first_payload["definitions"] == 4
    assert first_payload["inserted"] == 4
    assert first_payload["updated"] == 0
    assert first_payload["unchanged"] == 0
    assert first_payload["total"] == 4

    assert second_payload["inserted"] == 0
    assert second_payload["updated"] == 0
    assert second_payload["unchanged"] == 4
    assert second_payload["total"] == 4

    with sqlite3.connect(database_path) as connection:
        names = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM source_datasets ORDER BY name COLLATE NOCASE"
            )
        ]

    assert names == [
        "Alberta Funeral Services Regulatory Board",
        "Funeral Board of Manitoba",
        "Manual Canadian Funeral Home Source",
        "Nova Scotia Licensed Funeral Homes and Related Sellers",
    ]


def test_sources_list_is_deterministic() -> None:
    first = run_cli("sources", "list")
    second = run_cli("sources", "list")

    assert first.returncode == 0
    assert second.returncode == 0
    assert first.stdout == second.stdout

    payload = json.loads(first.stdout)

    assert len(payload) == 4

    names = [item["name"] for item in payload]
    assert names == sorted(names, key=str.casefold)

    for item in payload:
        assert item["source_type"]
        assert item["source_format"]
        assert item["trust_level"]
        assert item["coverage"]
        assert item["refresh_interval_days"] >= 1


def test_sources_show() -> None:
    result = run_cli(
        "sources",
        "show",
        "Alberta Funeral Services Regulatory Board",
    )

    assert result.returncode == 0

    payload = json.loads(result.stdout)
    assert payload["name"] == "Alberta Funeral Services Regulatory Board"
    assert payload["source_type"] == "regulator"
    assert payload["source_format"] == "html"
    assert payload["trust_level"] == "authoritative"
    assert payload["coverage"] == ["AB"]
    assert payload["enabled"] is True


def test_sources_show_is_case_insensitive() -> None:
    result = run_cli(
        "sources",
        "show",
        "alberta funeral services regulatory board",
    )

    assert result.returncode == 0

    payload = json.loads(result.stdout)
    assert payload["name"] == "Alberta Funeral Services Regulatory Board"


def test_sources_show_missing_returns_exit_four() -> None:
    result = run_cli(
        "sources",
        "show",
        "Definitely Missing Source",
    )

    assert result.returncode == 4
    assert "source registry error" in result.stderr
    assert "Source not found" in result.stderr


def test_website_people_commands_are_exposed() -> None:
    result = run_cli("website", "--help")
    assert result.returncode == 0
    assert "extract-people" in result.stdout
    assert "people" in result.stdout


def test_website_verify_help_is_exposed() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "canada_funeral_intel",
            "website",
            "verify",
            "--help",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "website_id" in result.stdout
    assert "--user-agent" in result.stdout
    assert "--timeout" in result.stdout
    assert "--max-redirects" in result.stdout


def test_website_checks_help_is_exposed() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "canada_funeral_intel",
            "website",
            "checks",
            "--help",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--website-id" in result.stdout
