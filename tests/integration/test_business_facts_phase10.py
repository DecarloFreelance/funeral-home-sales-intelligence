from __future__ import annotations

import sqlite3
from pathlib import Path

from canada_funeral_intel.business_intelligence.extraction import (
    BusinessFactPage,
    extract_business_facts,
)
from canada_funeral_intel.business_intelligence.reporting import (
    export_business_facts,
    summarize_business_facts,
)
from canada_funeral_intel.business_intelligence.storage import (
    list_business_facts,
    store_business_facts,
)
from canada_funeral_intel.storage.database import database_session
from canada_funeral_intel.storage.migrations import apply_pending_migrations
from tests.integration.test_website_phase8_people_integration import _seed

MIGRATIONS = Path(__file__).resolve().parents[2] / "database" / "migrations"


def test_business_fact_extraction_is_conservative_and_provenance_rich(
    tmp_path: Path,
) -> None:
    body = b"""<html><body><main><h1>About</h1><p>Family-owned since 1984. We speak English and French.</p><p>We offer chapel, pre-planning, livestreaming and grief resources.</p><p>Serving Calgary and Airdrie.</p></main><footer>Vendor testimonials</footer></body></html>"""
    page = BusinessFactPage(1, 2, 3, "https://example.ca/about", "about")
    result = extract_business_facts(
        body, content_type="text/html", status_code=200, page=page
    )
    keys = {item.fact_key for item in result.candidates}
    assert {
        "ownership_type",
        "founded_year",
        "languages_offered",
        "service_offering",
        "service_area",
    } <= keys
    assert all(item.evidence_snippet for item in result.candidates)
    assert not extract_business_facts(
        b"<html><body>We do not offer a chapel. Obituary archive</body></html>",
        content_type="text/html",
        status_code=200,
        page=page,
    ).candidates
    negative = extract_business_facts(
        b"<html><body><p>We do not offer a chapel or livestreaming.</p></body></html>",
        content_type="text/html",
        status_code=200,
        page=page,
    )
    assert not any(item.fact_key == "service_offering" for item in negative.candidates)


def test_business_fact_service_area_extraction_removes_known_page_noise() -> None:
    page = BusinessFactPage(1, 2, 3, "https://example.ca/about", "about")

    stonewall = extract_business_facts(
        b"<html><body>Serving the Communities of Stonewall, Teulon, Arborg, Warren, Woodlands, St</body></html>",
        content_type="text/html",
        status_code=200,
        page=page,
    )
    assert {
        item.raw_value
        for item in stonewall.candidates
        if item.fact_key == "service_area"
    } == {"Stonewall", "Teulon", "Arborg", "Warren", "Woodlands"}

    rae = extract_business_facts(
        b"<html><body>Serving you throughout Manitoba Rae</body></html>",
        content_type="text/html",
        status_code=200,
        page=page,
    )
    assert [item.raw_value for item in rae.candidates] == ["Manitoba"]

    assert not extract_business_facts(
        b"<html><body>Service Area - Tillwell Skip to content Call or Text</body></html>",
        content_type="text/html",
        status_code=200,
        page=page,
    ).candidates

    rae_address = extract_business_facts(
        b"<html><body>Serving you throughout Manitoba Rae | MB R0J 1Z0 | Tel: 1-204-759-2160</body></html>",
        content_type="text/html",
        status_code=200,
        page=page,
    )
    assert [item.raw_value for item in rae_address.candidates] == ["Manitoba"]

    tillwell = extract_business_facts(
        b"<html><body>Serving Manitoba raf</body></html>",
        content_type="text/html",
        status_code=200,
        page=page,
    )
    assert [item.raw_value for item in tillwell.candidates] == ["Manitoba"]

    assert not extract_business_facts(
        b"<html><body>Service Area - 1990 at the age of 78 years</body></html>",
        content_type="text/html",
        status_code=200,
        page=page,
    ).candidates


def test_business_fact_storage_is_idempotent_historical_and_conflict_safe(
    tmp_path: Path,
) -> None:
    with database_session(tmp_path / "facts.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        entity_id, website_id, page_id = _seed(connection)
        page = BusinessFactPage(
            page_id, website_id, entity_id, "https://example.ca/team", "team"
        )
        first = extract_business_facts(
            b"<html><body><p>Family-owned since 1984. Chapel available.</p></body></html>",
            content_type="text/html",
            status_code=200,
            page=page,
        )
        assert store_business_facts(connection, page=page, result=first).inserted == 3
        assert store_business_facts(connection, page=page, result=first).unchanged == 3
        second = extract_business_facts(
            b"<html><body><p>Family-owned since 1985. Chapel available.</p></body></html>",
            content_type="text/html",
            status_code=200,
            page=page,
        )
        assert store_business_facts(connection, page=page, result=second).inserted == 3
        rows = list_business_facts(connection, entity_id=entity_id)
        assert len(rows) == 6
        assert {row["entity_id"] for row in rows} == {entity_id}
        assert {row["website_page_id"] for row in rows} == {page_id}
        for row in rows:
            if row["fact_key"] != "service_offering":
                continue
            connection.execute(
                "INSERT INTO business_fact_agent_reviews (run_id, fact_id, disposition, confidence, rationale, evidence_reference, provider, model, prompt_version, artifact_sha256) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "test-run",
                    int(row["id"]),
                    "reject",
                    1.0,
                    "test rejection",
                    "https://example.ca/about",
                    "test",
                    "test-model",
                    "test-v1",
                    "a" * 64,
                ),
            )
        summaries = summarize_business_facts(connection, entity_id=entity_id)
        assert not any(row["fact_key"] == "service_offering" for row in summaries)
        assert any(
            row["fact_key"] == "founded_year" and row["state"] == "conflict"
            for row in summaries
        )
        first_dir, second_dir = tmp_path / "one", tmp_path / "two"
        export_business_facts(connection, first_dir, entity_id=entity_id)
        export_business_facts(connection, second_dir, entity_id=entity_id)
        assert (first_dir / "business_facts.csv").read_bytes() == (
            second_dir / "business_facts.csv"
        ).read_bytes()
        assert (first_dir / "business_fact_summary.csv").read_bytes() == (
            second_dir / "business_fact_summary.csv"
        ).read_bytes()


def test_business_fact_schema_rejects_invalid_scope_and_preserves_other_state(
    tmp_path: Path,
) -> None:
    with database_session(tmp_path / "constraints.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        entity_id, website_id, page_id = _seed(connection)
        before = connection.total_changes
        try:
            connection.execute(
                "INSERT INTO business_fact_observations (website_page_id, website_id, entity_id, source_url, page_kind, fact_key, value_kind, raw_value, normalized_value, scope, confidence, extraction_method, extractor_version, evidence_snippet, content_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'explicit', ?, ?, ?, ?, ?)",
                (
                    page_id,
                    website_id,
                    entity_id,
                    "https://example.ca/team",
                    "team",
                    "chapel",
                    "enum",
                    "chapel",
                    "chapel",
                    0.8,
                    "fixture",
                    "phase10-v1",
                    "chapel",
                    "a" * 64,
                ),
            )
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("invalid fact row was accepted")
        assert connection.total_changes == before
