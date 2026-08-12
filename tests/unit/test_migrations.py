from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from canada_funeral_intel.storage.migrations import (
    MigrationError,
    discover_migrations,
    generate_checksum,
    is_valid_migration_filename,
    parse_migration_description,
    parse_migration_filename,
    parse_migration_version,
)


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("0001_create_schema_migrations.sql", (1, "create_schema_migrations")),
        ("0042_add_people.sql", (42, "add_people")),
        ("9999_final.sql", (9999, "final")),
    ],
)
def test_parse_valid_filename(
    filename: str,
    expected: tuple[int, str],
) -> None:
    assert parse_migration_filename(filename) == expected


@pytest.mark.parametrize(
    "filename",
    [
        "0000_zero.sql",
        "001_short.sql",
        "00001_long.sql",
        "0001.sql",
        "0001_.sql",
        "0001_Uppercase.sql",
        "0001-hyphen.sql",
        "migration_0001.sql",
        "0001_description.txt",
        "notes.md",
    ],
)
def test_parse_invalid_filename(filename: str) -> None:
    with pytest.raises(MigrationError, match="migration filename|version"):
        parse_migration_filename(filename)
    assert not is_valid_migration_filename(filename)


def test_version_and_description_helpers() -> None:
    filename = "0012_add_website_checks.sql"
    assert parse_migration_version(filename) == 12
    assert parse_migration_description(filename) == "add_website_checks"
    assert is_valid_migration_filename(filename)


def test_checksum_is_stable_and_content_based(tmp_path: Path) -> None:
    migration = tmp_path / "0001_test.sql"
    payload = b"CREATE TABLE example (id INTEGER PRIMARY KEY);\n"
    migration.write_bytes(payload)

    expected = hashlib.sha256(payload).hexdigest()
    assert generate_checksum(migration) == expected
    assert generate_checksum(migration) == expected

    migration.write_bytes(payload + b"-- changed\n")
    assert generate_checksum(migration) != expected


def test_checksum_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(MigrationError, match="not found"):
        generate_checksum(tmp_path / "missing.sql")


def test_discovery_is_deterministic_and_numeric(tmp_path: Path) -> None:
    (tmp_path / "0010_tenth.sql").write_text("SELECT 10;\n", encoding="utf-8")
    (tmp_path / "0002_second.sql").write_text("SELECT 2;\n", encoding="utf-8")
    (tmp_path / "0001_first.sql").write_text("SELECT 1;\n", encoding="utf-8")

    migrations = discover_migrations(tmp_path)

    assert [migration.version for migration in migrations] == [1, 2, 10]
    assert [migration.description for migration in migrations] == [
        "first",
        "second",
        "tenth",
    ]
    assert all(len(migration.checksum) == 64 for migration in migrations)


def test_discovery_rejects_duplicate_versions(tmp_path: Path) -> None:
    (tmp_path / "0001_first.sql").write_text("SELECT 1;\n", encoding="utf-8")
    (tmp_path / "0001_duplicate.sql").write_text(
        "SELECT 2;\n",
        encoding="utf-8",
    )

    with pytest.raises(MigrationError, match="Duplicate migration version 0001"):
        discover_migrations(tmp_path)


def test_discovery_rejects_malformed_visible_files(tmp_path: Path) -> None:
    (tmp_path / "0001_valid.sql").write_text("SELECT 1;\n", encoding="utf-8")
    (tmp_path / "README.txt").write_text("not a migration\n", encoding="utf-8")

    with pytest.raises(MigrationError, match="Invalid migration filename"):
        discover_migrations(tmp_path)


def test_discovery_ignores_hidden_files_and_directories(tmp_path: Path) -> None:
    (tmp_path / ".keep").write_text("", encoding="utf-8")
    (tmp_path / "archive").mkdir()
    (tmp_path / "0001_valid.sql").write_text("SELECT 1;\n", encoding="utf-8")

    migrations = discover_migrations(tmp_path)

    assert [migration.name for migration in migrations] == ["0001_valid.sql"]


def test_discovery_allows_empty_directory(tmp_path: Path) -> None:
    assert discover_migrations(tmp_path) == []


def test_discovery_rejects_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(MigrationError, match="directory not found"):
        discover_migrations(tmp_path / "missing")
