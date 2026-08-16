from __future__ import annotations

import sqlite3
from pathlib import Path

from canada_funeral_intel.storage import database_session
from canada_funeral_intel.storage.migrations import apply_pending_migrations
from canada_funeral_intel.verification.manual import import_manual_website_evidence

ROOT = Path(__file__).resolve().parents[2]
MIGRATION_DIR = ROOT / "database" / "migrations"


def _seed(connection: sqlite3.Connection) -> int:
    connection.execute(
        """
        INSERT INTO source_datasets (name, source_type, jurisdiction)
        VALUES ('Manual Website Evidence Intake', 'manual', 'CA')
        """
    )
    cursor = connection.execute(
        """
        INSERT INTO entities (entity_type, canonical_name)
        VALUES ('branch', 'Example Funeral Home')
        """
    )
    assert cursor.lastrowid is not None
    connection.commit()
    return int(cursor.lastrowid)


def test_manual_website_evidence_is_provenanced_and_idempotent(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "manual-website.sqlite3"
    input_path = tmp_path / "website-evidence.csv"

    with database_session(database_path) as connection:
        apply_pending_migrations(connection, MIGRATION_DIR)
        entity_id = _seed(connection)
        input_path.write_text(
            "entity_id,website_url,source_url,note\n"
            f'{entity_id},https://Example.ca/locations/one,https://directory.test/one,"Name and address match"\n',
            encoding="utf-8",
        )

        first = import_manual_website_evidence(
            connection,
            input_path=input_path,
            source_dataset_id=1,
        )
        second = import_manual_website_evidence(
            connection,
            input_path=input_path,
            source_dataset_id=1,
        )

        assert first.rows_valid == 1
        assert first.candidates_inserted == 1
        assert first.evidence_inserted >= 1
        assert first.review_entries_queued == 1
        assert second.candidates_inserted == 0
        assert second.candidates_unchanged == 1
        assert second.evidence_inserted == 0

        website = connection.execute(
            "SELECT entity_id, normalized_url, is_primary, status FROM websites"
        ).fetchone()
        evidence = connection.execute(
            """
            SELECT evidence_class, derivation_method, raw_value
            FROM website_evidence
            """
        ).fetchone()
        source = connection.execute("SELECT raw_payload FROM source_records").fetchone()

        assert tuple(website) == (
            entity_id,
            "https://example.ca/locations/one",
            0,
            "review",
        )
        assert tuple(evidence) == (
            "manual",
            "manual_website_evidence_v1",
            "https://Example.ca/locations/one",
        )
        assert "Name and address match" in source["raw_payload"]


def test_manual_website_evidence_dry_run_does_not_write(tmp_path: Path) -> None:
    database_path = tmp_path / "manual-website-dry-run.sqlite3"
    input_path = tmp_path / "website-evidence.csv"

    with database_session(database_path) as connection:
        apply_pending_migrations(connection, MIGRATION_DIR)
        entity_id = _seed(connection)
        input_path.write_text(
            f"entity_id,website_url\n{entity_id},https://example.ca/\n",
            encoding="utf-8",
        )
        before = connection.total_changes
        result = import_manual_website_evidence(
            connection,
            input_path=input_path,
            source_dataset_id=1,
            dry_run=True,
        )

        assert result.dry_run is True
        assert result.rows_valid == 1
        assert result.candidates_inserted == 0
        assert connection.total_changes == before
        assert (
            connection.execute("SELECT COUNT(*) FROM source_records").fetchone()[0] == 0
        )
        assert connection.execute("SELECT COUNT(*) FROM websites").fetchone()[0] == 0


def test_manual_website_cli_import_commits_seed_boundary(tmp_path: Path) -> None:
    import json
    import os
    import subprocess
    import sys

    database_path = tmp_path / "manual-website-cli.sqlite3"
    input_path = tmp_path / "website-evidence.csv"
    input_path.write_text(
        "entity_id,website_url,source_url,note\n1,https://example.ca/,https://directory.test/1,match\n",
        encoding="utf-8",
    )
    with database_session(database_path) as connection:
        apply_pending_migrations(connection, MIGRATION_DIR)
        _seed(connection)

    environment = os.environ.copy()
    environment["DATABASE_PATH"] = str(database_path)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "canada_funeral_intel",
            "website",
            "import-manual",
            str(input_path),
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["candidates_inserted"] == 1
