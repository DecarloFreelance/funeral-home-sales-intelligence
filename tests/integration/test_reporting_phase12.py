from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from canada_funeral_intel.business_intelligence.extraction import (
    BusinessFactPage,
    extract_business_facts,
)
from canada_funeral_intel.business_intelligence.storage import store_business_facts
from canada_funeral_intel.reporting.exports import export_reports
from canada_funeral_intel.reporting.reports import (
    business_report,
    coverage_report,
    people_report,
    quality_report,
    summary_report,
)
from canada_funeral_intel.storage.database import database_session
from canada_funeral_intel.storage.migrations import apply_pending_migrations
from tests.integration.test_website_phase8_people_integration import _seed

MIGRATIONS = Path(__file__).resolve().parents[2] / "database" / "migrations"
REFERENCE = datetime(2026, 1, 1, tzinfo=UTC)


def test_empty_reports_have_explicit_denominators(tmp_path: Path) -> None:
    with database_session(tmp_path / "empty.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        report = summary_report(connection, reference_time=REFERENCE)
        assert report["report_version"] == "reporting-v1"
        assert all(metric["denominator"] == 0 and metric["percentage"] is None for metric in report["coverage"]["metrics"])
        assert report["people"]["people_count"] == 0


def test_coverage_and_business_conflict_counts_are_distinct(tmp_path: Path) -> None:
    with database_session(tmp_path / "reports.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        entity_id, website_id, page_id = _seed(connection)
        page = BusinessFactPage(page_id, website_id, entity_id, "https://example.ca/about", "about")
        for body in (b"<main>Family-owned since 1984.</main>", b"<main>Family-owned since 1985.</main>"):
            result = extract_business_facts(body, content_type="text/html", status_code=200, page=page)
            store_business_facts(connection, page=page, result=result)
        coverage = coverage_report(connection, reference_time=REFERENCE)
        metric = {row["definition_id"]: row for row in coverage["metrics"]}
        assert metric["entities_with_website"]["numerator"] == 1
        assert metric["entities_with_website"]["denominator"] == 1
        business = business_report(connection, include_historical=True, reference_time=REFERENCE)
        assert business["state_counts"]["conflict"] == 1
        assert sorted(business["fact_keys"][0]["values"]) == ["1984", "1985"]


def test_historical_business_facts_are_excluded_by_default(tmp_path: Path) -> None:
    with database_session(tmp_path / "historical.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        entity_id, website_id, page_id = _seed(connection)
        page = BusinessFactPage(page_id, website_id, entity_id, "https://example.ca/about", "about")
        for body in (b"<main>Family-owned since 1984.</main>", b"<main>Family-owned since 1985.</main>"):
            store_business_facts(connection, page=page, result=extract_business_facts(body, content_type="text/html", status_code=200, page=page))
        current = business_report(connection, reference_time=REFERENCE)
        historical = business_report(connection, include_historical=True, reference_time=REFERENCE)
        assert current["observation_count"] < historical["observation_count"]
        assert current["state_counts"]["conflict"] == 0
        assert historical["state_counts"]["conflict"] == 1


def test_quality_policy_and_people_report_are_read_only_and_export_deterministic(tmp_path: Path) -> None:
    with database_session(tmp_path / "export.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        _seed(connection)
        before = connection.total_changes
        assert quality_report(connection, reference_time=REFERENCE)["quality_policy_version"] == "quality-confidence-v1"
        assert people_report(connection, reference_time=REFERENCE)["people_count"] == 0
        first = tmp_path / "one"
        second = tmp_path / "two"
        export_reports(connection, first, reference_time=REFERENCE)
        export_reports(connection, second, reference_time=REFERENCE)
        assert connection.total_changes == before
        for path in first.iterdir():
            assert path.read_bytes() == (second / path.name).read_bytes()
