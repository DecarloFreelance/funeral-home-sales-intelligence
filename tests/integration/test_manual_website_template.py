from __future__ import annotations

import csv
from pathlib import Path

from canada_funeral_intel.storage import database_session
from canada_funeral_intel.storage.migrations import apply_pending_migrations
from canada_funeral_intel.verification.manual import export_manual_website_template

ROOT = Path(__file__).resolve().parents[2]
MIGRATION_DIR = ROOT / "database" / "migrations"


def test_manual_website_template_is_deterministic_and_excludes_candidates(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "template.sqlite3"
    first_path = tmp_path / "first.csv"
    second_path = tmp_path / "second.csv"

    with database_session(database_path) as connection:
        apply_pending_migrations(connection, MIGRATION_DIR)
        connection.execute(
            "INSERT INTO entities (entity_type, canonical_name) VALUES ('branch', ?)",
            ("=Formula Funeral Home",),
        )
        connection.execute(
            "INSERT INTO entities (entity_type, canonical_name) VALUES ('branch', ?)",
            ("Covered Funeral Home",),
        )
        connection.execute(
            """
            INSERT INTO websites (entity_id, url, normalized_url, domain, discovery_method)
            VALUES (2, 'https://covered.example/', 'https://covered.example/', 'covered.example', 'fixture')
            """
        )
        connection.commit()

        first = export_manual_website_template(
            connection,
            output_path=first_path,
        )
        second = export_manual_website_template(
            connection,
            output_path=second_path,
        )

    assert first["rows"] == 1
    assert second["rows"] == 1
    assert first_path.read_bytes() == second_path.read_bytes()
    with first_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["entity_id"] == "1"
    assert rows[0]["entity_name"] == "'=Formula Funeral Home"
    assert rows[0]["website_url"] == ""
