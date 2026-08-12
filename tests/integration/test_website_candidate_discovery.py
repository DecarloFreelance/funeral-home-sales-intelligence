from __future__ import annotations

import sqlite3
from pathlib import Path

from canada_funeral_intel.storage import database_session
from canada_funeral_intel.storage.migrations import apply_pending_migrations
from canada_funeral_intel.verification.discovery import discover_website_candidates

ROOT = Path(__file__).resolve().parents[2]
MIGRATION_DIR = ROOT / "database" / "migrations"


def _seed_dataset(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO source_datasets (
            name, source_type, publisher, jurisdiction
        )
        VALUES ('website-fixture', 'manual', 'fixture', 'CA')
        """
    )


def _seed_entity(
    connection: sqlite3.Connection,
    *,
    name: str,
    entity_type: str = "organization",
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO entities (entity_type, canonical_name)
        VALUES (?, ?)
        """,
        (entity_type, name),
    )
    assert cursor.lastrowid is not None
    return int(cursor.lastrowid)


def _seed_source_record(
    connection: sqlite3.Connection,
    *,
    entity_id: int,
    external_id: str,
    website_url: str | None = None,
    domain: str | None = None,
    provenance_url: str | None = None,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO source_records (
            source_dataset_id,
            external_record_id,
            raw_payload,
            payload_format,
            source_url,
            retrieved_at,
            checksum
        )
        VALUES (1, ?, '{}', 'json', ?, '2026-01-01T00:00:00Z', ?)
        """,
        (external_id, provenance_url, f"checksum-{external_id}"),
    )
    assert cursor.lastrowid is not None
    source_record_id = int(cursor.lastrowid)

    connection.execute(
        """
        INSERT INTO entity_source_records (
            entity_id, source_record_id, membership_role
        )
        VALUES (?, ?, 'location')
        """,
        (entity_id, source_record_id),
    )

    if website_url is not None:
        connection.execute(
            """
            INSERT INTO normalized_values (
                source_record_id,
                field_name,
                original_value,
                normalized_value,
                normalizer_name,
                normalizer_version,
                normalized_at
            )
            VALUES (?, 'url', ?, ?, 'url', '1', '2026-01-01T00:00:00Z')
            """,
            (source_record_id, website_url, website_url),
        )

    if domain is not None:
        connection.execute(
            """
            INSERT INTO normalized_values (
                source_record_id,
                field_name,
                original_value,
                normalized_value,
                normalizer_name,
                normalizer_version,
                normalized_at
            )
            VALUES (?, 'domain', ?, ?, 'domain', '1', '2026-01-01T00:00:00Z')
            """,
            (source_record_id, domain, domain),
        )

    return source_record_id


def test_discovery_creates_candidate_with_provenance_evidence(tmp_path: Path) -> None:
    database_path = tmp_path / "candidate.sqlite3"

    with database_session(database_path) as connection:
        apply_pending_migrations(connection, MIGRATION_DIR)
        _seed_dataset(connection)
        entity_id = _seed_entity(connection, name="Prairie Funeral Home")
        source_record_id = _seed_source_record(
            connection,
            entity_id=entity_id,
            external_id="one",
            website_url="https://prairiefuneral.ca/",
            domain="prairiefuneral.ca",
            provenance_url="https://registry.example/one",
        )
        connection.commit()

        result = discover_website_candidates(connection)

        assert result.candidates_inserted == 1
        assert result.evidence_inserted == 3
        row = connection.execute(
            """
            SELECT entity_id, source_record_id, domain, website_kind,
                   confidence, status, is_primary
            FROM websites
            """
        ).fetchone()
        assert tuple(row) == (
            entity_id,
            source_record_id,
            "prairiefuneral.ca",
            "candidate",
            0.75,
            "candidate",
            0,
        )
        evidence_types = {
            item[0]
            for item in connection.execute(
                "SELECT evidence_type FROM website_evidence"
            ).fetchall()
        }
        assert evidence_types == {"source_url", "normalized_url", "domain"}


def test_discovery_is_idempotent(tmp_path: Path) -> None:
    database_path = tmp_path / "idempotent.sqlite3"

    with database_session(database_path) as connection:
        apply_pending_migrations(connection, MIGRATION_DIR)
        _seed_dataset(connection)
        entity_id = _seed_entity(connection, name="Fixture")
        _seed_source_record(
            connection,
            entity_id=entity_id,
            external_id="one",
            website_url="https://fixture.ca/",
            domain="fixture.ca",
        )
        connection.commit()

        first = discover_website_candidates(connection)
        second = discover_website_candidates(connection)

        assert first.candidates_inserted == 1
        assert second.candidates_inserted == 0
        assert second.candidates_unchanged == 1
        assert second.evidence_inserted == 0
        assert connection.execute("SELECT COUNT(*) FROM websites").fetchone()[0] == 1


def test_shared_domain_candidates_are_queued_for_review(tmp_path: Path) -> None:
    database_path = tmp_path / "shared.sqlite3"

    with database_session(database_path) as connection:
        apply_pending_migrations(connection, MIGRATION_DIR)
        _seed_dataset(connection)
        first_entity = _seed_entity(connection, name="North Group")
        second_entity = _seed_entity(connection, name="South Group")
        _seed_source_record(
            connection,
            entity_id=first_entity,
            external_id="north",
            website_url="https://sharedfuneral.ca/",
            domain="sharedfuneral.ca",
        )
        _seed_source_record(
            connection,
            entity_id=second_entity,
            external_id="south",
            website_url="https://sharedfuneral.ca/",
            domain="sharedfuneral.ca",
        )
        connection.commit()

        result = discover_website_candidates(connection)

        assert result.shared_domain_candidates == 2
        assert result.review_entries_queued == 2
        kinds = [
            row[0]
            for row in connection.execute(
                "SELECT website_kind FROM websites ORDER BY entity_id"
            ).fetchall()
        ]
        assert kinds == ["shared", "shared"]
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM website_review_queue WHERE status = 'pending'"
            ).fetchone()[0]
            == 2
        )


def test_branch_specific_path_is_classified_as_branch_page(tmp_path: Path) -> None:
    database_path = tmp_path / "branch.sqlite3"

    with database_session(database_path) as connection:
        apply_pending_migrations(connection, MIGRATION_DIR)
        _seed_dataset(connection)
        entity_id = _seed_entity(
            connection,
            name="Calgary Branch",
            entity_type="branch",
        )
        _seed_source_record(
            connection,
            entity_id=entity_id,
            external_id="branch",
            website_url="https://group.ca/locations/calgary",
            domain="group.ca",
        )
        connection.commit()

        result = discover_website_candidates(connection)

        assert result.branch_page_candidates == 1
        row = connection.execute(
            "SELECT website_kind, confidence, status FROM websites"
        ).fetchone()
        assert tuple(row) == ("branch", 0.85, "candidate")
        assert (
            connection.execute(
                """
                SELECT COUNT(*)
                FROM website_evidence
                WHERE evidence_type = 'location'
                """
            ).fetchone()[0]
            == 1
        )


def test_social_profile_is_never_promoted_and_is_queued(tmp_path: Path) -> None:
    database_path = tmp_path / "social.sqlite3"

    with database_session(database_path) as connection:
        apply_pending_migrations(connection, MIGRATION_DIR)
        _seed_dataset(connection)
        entity_id = _seed_entity(connection, name="Social Fixture")
        _seed_source_record(
            connection,
            entity_id=entity_id,
            external_id="social",
            website_url="https://www.facebook.com/examplefuneral",
            domain="facebook.com",
        )
        connection.commit()

        result = discover_website_candidates(connection)

        assert result.social_candidates == 1
        assert result.review_entries_queued == 1
        row = connection.execute(
            """
            SELECT website_kind, confidence, status, is_primary
            FROM websites
            """
        ).fetchone()
        assert tuple(row) == ("social", 0.20, "review", 0)


def test_secondary_domain_is_classified_as_alternate(tmp_path: Path) -> None:
    database_path = tmp_path / "alternate.sqlite3"

    with database_session(database_path) as connection:
        apply_pending_migrations(connection, MIGRATION_DIR)
        _seed_dataset(connection)
        entity_id = _seed_entity(connection, name="Alternate Fixture")
        _seed_source_record(
            connection,
            entity_id=entity_id,
            external_id="primary-1",
            website_url="https://mainfuneral.ca/",
            domain="mainfuneral.ca",
        )
        _seed_source_record(
            connection,
            entity_id=entity_id,
            external_id="primary-2",
            website_url="https://mainfuneral.ca/contact",
            domain="mainfuneral.ca",
        )
        _seed_source_record(
            connection,
            entity_id=entity_id,
            external_id="alternate",
            website_url="https://legacyfuneral.ca/",
            domain="legacyfuneral.ca",
        )
        connection.commit()

        result = discover_website_candidates(connection)

        assert result.alternate_domain_candidates == 1
        alternate_row = connection.execute(
            """
            SELECT website_kind, confidence, status
            FROM websites
            WHERE domain = 'legacyfuneral.ca'
            """
        ).fetchone()
        assert tuple(alternate_row) == ("alternate", 0.55, "review")


def test_domain_only_signal_synthesizes_https_root_candidate(tmp_path: Path) -> None:
    database_path = tmp_path / "domain-only.sqlite3"

    with database_session(database_path) as connection:
        apply_pending_migrations(connection, MIGRATION_DIR)
        _seed_dataset(connection)
        entity_id = _seed_entity(connection, name="Domain Fixture")
        _seed_source_record(
            connection,
            entity_id=entity_id,
            external_id="domain-only",
            domain="domainfixture.ca",
        )
        connection.commit()

        result = discover_website_candidates(connection)

        assert result.candidates_inserted == 1
        row = connection.execute(
            "SELECT normalized_url, domain FROM websites"
        ).fetchone()
        assert tuple(row) == ("https://domainfixture.ca/", "domainfixture.ca")
