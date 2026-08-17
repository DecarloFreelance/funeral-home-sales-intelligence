from __future__ import annotations

import json
from pathlib import Path

from canada_funeral_intel.reporting.public_directory import (
    PUBLIC_DIRECTORY_VERSION,
    _clean_public_person_name,
    build_public_directory,
    write_public_directory,
)


def test_public_person_name_cleanup_removes_legacy_extraction_noise() -> None:
    assert _clean_public_person_name("Patricia A. Sweryd Vice") == "Patricia A. Sweryd"
    assert _clean_public_person_name("Jack Joyce Lumbard Jack") == "Jack & Joyce Lumbard"
    assert _clean_public_person_name("Wade Kelly Lumbard Wade") == "Wade & Kelly Lumbard"
from canada_funeral_intel.storage.database import database_session
from canada_funeral_intel.storage.migrations import apply_pending_migrations

MIGRATIONS = Path(__file__).resolve().parents[2] / "database" / "migrations"


def _seed_public_fixture(database_path: Path) -> None:
    with database_session(database_path) as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        connection.execute(
            "INSERT INTO source_datasets (name, source_type, jurisdiction) VALUES (?, ?, ?)",
            ("Fixture Public Source", "test", "CA"),
        )
        source_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        connection.execute(
            """
            INSERT INTO source_records (
                source_dataset_id, external_record_id, raw_payload,
                payload_format, source_url, retrieved_at, checksum
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_id,
                "fixture-1",
                '{"private_note":"do-not-publish"}',
                "json",
                "fixture://source",
                "2026-01-01T00:00:00Z",
                "fixture-checksum",
            ),
        )
        source_record_id = int(
            connection.execute("SELECT last_insert_rowid()").fetchone()[0]
        )
        connection.execute(
            "INSERT INTO entities (entity_type, canonical_name) VALUES (?, ?)",
            ("branch", "Fixture Funeral Home"),
        )
        entity_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        connection.execute(
            "INSERT INTO entity_source_records (entity_id, source_record_id) VALUES (?, ?)",
            (entity_id, source_record_id),
        )
        for field_name, value in (("city", "Calgary"), ("province", "AB")):
            connection.execute(
                """
                INSERT INTO normalized_values (
                    source_record_id, field_name, normalized_value,
                    normalizer_name, normalizer_version, normalized_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    source_record_id,
                    field_name,
                    value,
                    "fixture",
                    "1",
                    "2026-01-01T00:00:00Z",
                ),
            )
        connection.execute(
            """
            INSERT INTO normalized_values (
                source_record_id, field_name, original_value, normalized_value,
                normalizer_name, normalizer_version, normalized_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_record_id,
                "business_name",
                "Fixture Funeral Home",
                "fixture funeral home",
                "fixture",
                "1",
                "2026-01-01T00:00:00Z",
            ),
        )
        connection.execute(
            """
            INSERT INTO websites (
                entity_id, source_record_id, url, normalized_url, domain,
                discovery_method, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entity_id,
                source_record_id,
                "https://fixture.example/",
                "https://fixture.example/",
                "fixture.example",
                "source_url",
                "review",
            ),
        )
        connection.commit()


def test_public_directory_is_curated_and_deterministic(tmp_path: Path) -> None:
    database_path = tmp_path / "public.sqlite3"
    _seed_public_fixture(database_path)

    payload = build_public_directory(database_path)
    serialized = json.dumps(payload, sort_keys=True)

    assert payload["directory_version"] == PUBLIC_DIRECTORY_VERSION
    assert payload["record_count"] == 1
    assert payload["records"] == [
        {
            "city": "Calgary",
            "entity_id": 1,
            "entity_type": "branch",
            "name": "Fixture Funeral Home",
            "province": "AB",
            "source_names": ["Fixture Public Source"],
            "website_status": "review",
            "website_url": "https://fixture.example/",
            "business_facts": {},
            "people": [],
        }
    ]
    assert "private_note" not in serialized
    assert "raw_payload" not in serialized

    output_path = tmp_path / "site" / "directory.json"
    written = write_public_directory(database_path, output_path)
    assert json.loads(output_path.read_text(encoding="utf-8")) == written
