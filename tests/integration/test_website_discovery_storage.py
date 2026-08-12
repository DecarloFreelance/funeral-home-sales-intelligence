from __future__ import annotations

import sqlite3
from pathlib import Path

from canada_funeral_intel.storage import database_session
from canada_funeral_intel.storage.migrations import apply_pending_migrations
from canada_funeral_intel.verification.models import (
    WebsiteEvidence,
    WebsiteEvidenceType,
)
from canada_funeral_intel.verification.storage import (
    list_website_candidates,
    make_website_candidate,
    queue_website_for_review,
    upsert_website_candidate,
)

ROOT = Path(__file__).resolve().parents[2]
MIGRATION_DIR = ROOT / "database" / "migrations"


def _seed_entity(connection: sqlite3.Connection) -> tuple[int, int]:
    connection.execute(
        """
        INSERT INTO source_datasets (
            name, source_type, publisher, jurisdiction
        )
        VALUES ('fixture', 'manual', 'fixture', 'CA')
        """
    )
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
        VALUES (
            1,
            'fixture-1',
            '{}',
            'json',
            'https://example.test/record',
            '2026-01-01T00:00:00Z',
            'fixture-checksum'
        )
        """
    )
    assert cursor.lastrowid is not None
    source_record_id = int(cursor.lastrowid)

    cursor = connection.execute(
        """
        INSERT INTO entities (entity_type, canonical_name)
        VALUES ('organization', 'Fixture Funeral Home')
        """
    )
    assert cursor.lastrowid is not None
    entity_id = int(cursor.lastrowid)

    connection.execute(
        """
        INSERT INTO entity_source_records (
            entity_id, source_record_id, membership_role
        )
        VALUES (?, ?, 'organization')
        """,
        (entity_id, source_record_id),
    )
    connection.commit()
    return entity_id, source_record_id


def test_website_schema_and_candidate_persistence(tmp_path: Path) -> None:
    database_path = tmp_path / "websites.sqlite3"

    with database_session(database_path) as connection:
        result = apply_pending_migrations(connection, MIGRATION_DIR)
        assert result.status.current_version == 18

        entity_id, source_record_id = _seed_entity(connection)
        candidate = make_website_candidate(
            entity_id=entity_id,
            source_record_id=source_record_id,
            url="Example.CA/contact#staff",
            discovery_method="source_record_url",
            confidence=0.72,
        )
        evidence = (
            WebsiteEvidence(
                evidence_type=WebsiteEvidenceType.SOURCE_URL,
                source_record_id=source_record_id,
                evidence_value="https://example.test/record",
                contribution=0.25,
            ),
            WebsiteEvidence(
                evidence_type=WebsiteEvidenceType.DOMAIN,
                source_record_id=source_record_id,
                evidence_value="example.ca",
                contribution=0.30,
            ),
        )

        first = upsert_website_candidate(
            connection,
            candidate,
            evidence=evidence,
        )
        second = upsert_website_candidate(
            connection,
            candidate,
            evidence=evidence,
        )

        assert first.inserted is True
        assert first.evidence_inserted == 2
        assert second.inserted is False
        assert second.evidence_inserted == 0

        rows = list_website_candidates(connection, entity_id=entity_id)
        assert len(rows) == 1
        assert rows[0].normalized_url == "https://example.ca/contact"
        assert rows[0].domain == "example.ca"
        assert rows[0].confidence == 0.72


def test_shared_domain_is_allowed_across_entities(tmp_path: Path) -> None:
    database_path = tmp_path / "shared.sqlite3"

    with database_session(database_path) as connection:
        apply_pending_migrations(connection, MIGRATION_DIR)

        first_entity, _ = _seed_entity(connection)
        cursor = connection.execute(
            """
            INSERT INTO entities (entity_type, canonical_name)
            VALUES ('branch', 'Fixture Branch')
            """
        )
        assert cursor.lastrowid is not None
        second_entity = int(cursor.lastrowid)
        connection.commit()

        first = make_website_candidate(
            entity_id=first_entity,
            url="https://example.ca/",
            discovery_method="manual",
            confidence=0.8,
        )
        second = make_website_candidate(
            entity_id=second_entity,
            url="https://example.ca/location/calgary",
            discovery_method="manual",
            confidence=0.7,
        )

        upsert_website_candidate(connection, first)
        upsert_website_candidate(connection, second)

        count = connection.execute(
            "SELECT COUNT(*) FROM websites WHERE domain = 'example.ca'"
        ).fetchone()[0]
        assert count == 2


def test_website_review_queue_is_idempotent(tmp_path: Path) -> None:
    database_path = tmp_path / "review.sqlite3"

    with database_session(database_path) as connection:
        apply_pending_migrations(connection, MIGRATION_DIR)
        entity_id, _ = _seed_entity(connection)
        candidate = make_website_candidate(
            entity_id=entity_id,
            url="https://example.ca/",
            discovery_method="manual",
            confidence=0.51,
        )
        website_id = upsert_website_candidate(
            connection,
            candidate,
        ).website_id

        first_queue_id = queue_website_for_review(connection, website_id)
        second_queue_id = queue_website_for_review(connection, website_id)

        assert first_queue_id == second_queue_id
        row = connection.execute(
            """
            SELECT rq.status, w.status
            FROM website_review_queue AS rq
            JOIN websites AS w ON w.id = rq.website_id
            WHERE rq.id = ?
            """,
            (first_queue_id,),
        ).fetchone()
        assert tuple(row) == ("pending", "review")
