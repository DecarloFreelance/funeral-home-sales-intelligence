from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from canada_funeral_intel.collectors.source_registry import (
    SourceDefinition,
    SourceFormat,
    SourceType,
    TrustLevel,
    load_source_registry,
)
from canada_funeral_intel.collectors.source_registry_storage import (
    seed_source_registry,
)
from canada_funeral_intel.storage import database_session
from canada_funeral_intel.storage.migrations import apply_pending_migrations

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "database" / "migrations"
REGISTRY = ROOT / "config" / "sources.json"


def migrate(path: Path) -> None:
    with database_session(path) as connection:
        status = apply_pending_migrations(connection, MIGRATIONS).status
        assert status.current_version == 13


def definition(name: str = "Example Source") -> SourceDefinition:
    return SourceDefinition(
        name=name,
        source_type=SourceType.REGULATOR,
        source_format=SourceFormat.HTML,
        trust_level=TrustLevel.AUTHORITATIVE,
        coverage=("AB",),
        refresh_interval_days=30,
        enabled=True,
        source_url="https://example.test/source",
        publisher="Example Publisher",
        jurisdiction="AB",
        license_name="Example Licence",
        license_url="https://example.test/licence",
        licensing_notes="Public metadata.",
        notes="Test source.",
    )


def test_seed_inserts_source_registry_record(tmp_path: Path) -> None:
    database_path = tmp_path / "registry.sqlite3"
    migrate(database_path)

    item = definition()

    with database_session(database_path) as connection:
        result = seed_source_registry(connection, (item,))
        connection.commit()

        row = connection.execute(
            "SELECT * FROM source_datasets WHERE name = ?",
            (item.name,),
        ).fetchone()

    assert result.inserted == 1
    assert result.updated == 0
    assert result.unchanged == 0
    assert result.total == 1
    assert row is not None
    assert row["source_type"] == "regulator"
    assert row["source_format"] == "html"
    assert row["trust_level"] == "authoritative"
    assert row["refresh_interval_days"] == 30
    assert json.loads(row["coverage"]) == ["AB"]
    assert row["is_active"] == 1


def test_seed_is_idempotent(tmp_path: Path) -> None:
    database_path = tmp_path / "registry.sqlite3"
    migrate(database_path)

    item = definition()

    with database_session(database_path) as connection:
        first = seed_source_registry(connection, (item,))
        connection.commit()
        before = connection.execute(
            "SELECT created_at, updated_at FROM source_datasets WHERE name = ?",
            (item.name,),
        ).fetchone()

        second = seed_source_registry(connection, (item,))
        connection.commit()
        after = connection.execute(
            "SELECT created_at, updated_at FROM source_datasets WHERE name = ?",
            (item.name,),
        ).fetchone()

    assert first.inserted == 1
    assert second.inserted == 0
    assert second.updated == 0
    assert second.unchanged == 1
    assert before is not None
    assert after is not None
    assert tuple(before) == tuple(after)


def test_seed_updates_changed_metadata(tmp_path: Path) -> None:
    database_path = tmp_path / "registry.sqlite3"
    migrate(database_path)

    original = definition()
    changed = replace(
        original,
        trust_level=TrustLevel.HIGH,
        refresh_interval_days=14,
        coverage=("AB", "BC"),
        notes="Changed metadata.",
    )

    with database_session(database_path) as connection:
        seed_source_registry(connection, (original,))
        connection.commit()

        result = seed_source_registry(connection, (changed,))
        connection.commit()

        row = connection.execute(
            """
            SELECT trust_level, refresh_interval_days, coverage, notes
            FROM source_datasets
            WHERE name = ?
            """,
            (original.name,),
        ).fetchone()

    assert result.inserted == 0
    assert result.updated == 1
    assert result.unchanged == 0
    assert row is not None
    assert row["trust_level"] == "high"
    assert row["refresh_interval_days"] == 14
    assert json.loads(row["coverage"]) == ["AB", "BC"]
    assert row["notes"] == "Changed metadata."


def test_seed_updates_enabled_state(tmp_path: Path) -> None:
    database_path = tmp_path / "registry.sqlite3"
    migrate(database_path)

    enabled = definition()
    disabled = replace(enabled, enabled=False)

    with database_session(database_path) as connection:
        seed_source_registry(connection, (enabled,))
        connection.commit()

        result = seed_source_registry(connection, (disabled,))
        connection.commit()

        row = connection.execute(
            "SELECT is_active FROM source_datasets WHERE name = ?",
            (enabled.name,),
        ).fetchone()

    assert result.updated == 1
    assert row is not None
    assert row["is_active"] == 0


def test_seed_project_registry_is_deterministic(tmp_path: Path) -> None:
    database_path = tmp_path / "registry.sqlite3"
    migrate(database_path)
    registry = load_source_registry(REGISTRY)

    with database_session(database_path) as connection:
        first = seed_source_registry(connection, registry)
        connection.commit()

        second = seed_source_registry(connection, registry)
        connection.commit()

        names = [
            row["name"]
            for row in connection.execute(
                "SELECT name FROM source_datasets ORDER BY name COLLATE NOCASE"
            )
        ]

    assert first.inserted == len(registry)
    assert first.updated == 0
    assert second.inserted == 0
    assert second.updated == 0
    assert second.unchanged == len(registry)
    assert names == [item.name for item in registry]


def test_seed_survives_database_reopen(tmp_path: Path) -> None:
    database_path = tmp_path / "registry.sqlite3"
    migrate(database_path)
    item = definition()

    with database_session(database_path) as connection:
        seed_source_registry(connection, (item,))
        connection.commit()

    with database_session(database_path) as connection:
        row = connection.execute(
            """
            SELECT name, publisher, jurisdiction, source_format, trust_level
            FROM source_datasets
            WHERE name = ?
            """,
            (item.name,),
        ).fetchone()

    assert row is not None
    assert row["name"] == item.name
    assert row["publisher"] == item.publisher
    assert row["jurisdiction"] == "AB"
    assert row["source_format"] == "html"
    assert row["trust_level"] == "authoritative"
