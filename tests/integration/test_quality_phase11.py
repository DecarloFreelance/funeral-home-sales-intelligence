from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from canada_funeral_intel.business_intelligence.extraction import (
    BusinessFactPage,
    extract_business_facts,
)
from canada_funeral_intel.business_intelligence.storage import store_business_facts
from canada_funeral_intel.quality.reporting import export_quality, quality_summary
from canada_funeral_intel.quality.scoring import score_one
from canada_funeral_intel.storage.database import database_session
from canada_funeral_intel.storage.migrations import apply_pending_migrations
from tests.integration.test_website_phase8_people_integration import _seed

MIGRATIONS = Path(__file__).resolve().parents[2] / "database" / "migrations"
REFERENCE = datetime(2026, 1, 1, tzinfo=UTC)


def _facts(
    connection: sqlite3.Connection,
    entity_id: int,
    website_id: int,
    page_id: int,
    body: bytes,
) -> None:
    page = BusinessFactPage(
        page_id, website_id, entity_id, "https://example.ca/about", "about"
    )
    store_business_facts(
        connection,
        page=page,
        result=extract_business_facts(
            body, content_type="text/html", status_code=200, page=page
        ),
    )


def test_quality_scores_business_facts_with_provenance_and_conflict(
    tmp_path: Path,
) -> None:
    with database_session(tmp_path / "quality.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        entity_id, website_id, page_id = _seed(connection)
        _facts(
            connection,
            entity_id,
            website_id,
            page_id,
            b"<main>Family-owned since 1984. We offer chapel.</main>",
        )
        _facts(
            connection,
            entity_id,
            website_id,
            page_id,
            b"<main>Family-owned since 1985. We offer chapel.</main>",
        )
        rows = quality_summary(
            connection,
            subject_type="business_fact",
            reference_time=REFERENCE,
            entity_id=entity_id,
            include_historical=True,
        )
        years = [
            row
            for row in rows
            if row["evidence"].get("fact_id")
            and "conflicting_values" in row["warnings"]
        ]
        assert years
        assert all(row["policy_version"] == "quality-confidence-v1" for row in rows)
        assert all(
            0 <= row["components"][name] <= 100
            for row in rows
            for name in row["components"]
            if row["components"][name] is not None
        )
        assert len({row["input_fingerprint"] for row in rows}) == len(rows)


def test_quality_repetition_does_not_require_independent_rows(tmp_path: Path) -> None:
    with database_session(tmp_path / "quality.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        entity_id, website_id, page_id = _seed(connection)
        body = b"<main>Family-owned since 1984.</main>"
        _facts(connection, entity_id, website_id, page_id, body)
        first = score_one(connection, "business_fact", 1, reference_time=REFERENCE)
        assert first["evidence"]["snapshot_count"] == 1
        assert first["warnings"] == []
        _facts(connection, entity_id, website_id, page_id, body)
        second = score_one(connection, "business_fact", 1, reference_time=REFERENCE)
        assert second["input_fingerprint"] == first["input_fingerprint"]


def test_quality_no_evidence_is_explicit_and_read_only(tmp_path: Path) -> None:
    with database_session(tmp_path / "quality.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        entity_id, _, _ = _seed(connection)
        before = connection.total_changes
        result = score_one(connection, "entity", entity_id, reference_time=REFERENCE)
        assert result["readiness"] == "insufficient_evidence"
        assert "missing_source_record" in result["reasons"]
        assert connection.total_changes == before


def test_quality_invalid_subject_and_exports_are_deterministic(tmp_path: Path) -> None:
    with database_session(tmp_path / "quality.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        entity_id, website_id, page_id = _seed(connection)
        _facts(
            connection,
            entity_id,
            website_id,
            page_id,
            b"<main>Family-owned since 1984.</main>",
        )
        with pytest.raises(ValueError, match="not found"):
            score_one(connection, "entity", 999, reference_time=REFERENCE)
        first = tmp_path / "one"
        second = tmp_path / "two"
        export_quality(connection, first, reference_time=REFERENCE)
        export_quality(connection, second, reference_time=REFERENCE)
        for path in first.iterdir():
            assert path.read_bytes() == (second / path.name).read_bytes()


def test_quality_subject_queries_are_bounded_and_structured(tmp_path: Path) -> None:
    with database_session(tmp_path / "quality.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        entity_id, website_id, page_id = _seed(connection)
        _facts(
            connection,
            entity_id,
            website_id,
            page_id,
            b"<main>Family-owned since 1984.</main>",
        )
        for subject_type in ("entity", "website", "website_page", "business_fact"):
            rows = quality_summary(
                connection, subject_type=subject_type, reference_time=REFERENCE
            )
            assert rows
            assert all(
                {
                    "policy_version",
                    "components",
                    "overall_score",
                    "readiness",
                    "input_fingerprint",
                }
                <= row.keys()
                for row in rows
            )


def test_rejected_person_observations_are_not_positive_quality_evidence(
    tmp_path: Path,
) -> None:
    with database_session(tmp_path / "quality.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        entity_id, website_id, page_id = _seed(connection)
        observation = connection.execute(
            """INSERT INTO website_page_person_observations
            (website_page_id, website_id, entity_id, observed_name, normalized_name,
             role_title, normalized_role, confidence, extraction_method,
             extractor_version, evidence_snippet, source_url, content_hash)
            VALUES (?, ?, ?, 'Alex Doe', 'alex doe', 'Director', 'director',
                    0.9, 'structured_role_block', 'fixture-v1', 'Alex Doe Director',
                    'https://example.ca/team', ?)""",
            (page_id, website_id, entity_id, "a" * 64),
        )
        observation_id = int(observation.lastrowid)
        connection.execute(
            "INSERT INTO person_observation_review_queue (observation_id, status) VALUES (?, 'rejected')",
            (observation_id,),
        )
        person = connection.execute(
            "INSERT INTO people (canonical_name, normalized_name) VALUES ('Alex Doe', 'alex doe')"
        )
        person_id = int(person.lastrowid)
        connection.execute(
            "INSERT INTO person_evidence (person_id, observation_id, review_decision) VALUES (?, ?, 'rejected')",
            (person_id, observation_id),
        )
        connection.commit()
        result = score_one(connection, "person", person_id, reference_time=REFERENCE)
        assert result["evidence"]["evidence_count"] == 0
        assert result["readiness"] == "insufficient_evidence"
