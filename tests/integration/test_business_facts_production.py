from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from canada_funeral_intel.business_intelligence.cli import (
    run_business_facts_export,
    run_business_facts_extract,
    run_business_facts_list,
    run_business_facts_summary,
)
from canada_funeral_intel.business_intelligence.storage import list_business_facts
from canada_funeral_intel.cli import main
from canada_funeral_intel.collectors.importers import ImportFormat
from canada_funeral_intel.pipeline.orchestrator import PipelineInput, create_run
from canada_funeral_intel.storage.database import database_session
from canada_funeral_intel.storage.migrations import apply_pending_migrations
from canada_funeral_intel.verification.page_discovery import (
    DiscoveredPage,
    classify_page,
    discover_website_pages,
    upsert_website_page,
)
from canada_funeral_intel.verification.probe import HTTPProbeResult, WebsiteProbeError
from tests.integration.test_website_phase8_people_integration import _seed

MIGRATIONS = Path(__file__).resolve().parents[2] / "database" / "migrations"


def _probe_result(
    url: str,
    body: bytes,
    *,
    status: int = 200,
    content_type: str = "text/html",
) -> HTTPProbeResult:
    return HTTPProbeResult(
        requested_url=url,
        final_url=url,
        status_code=status,
        redirect_count=0,
        response_time_ms=1,
        content_type=content_type,
        canonical_url=None,
        error_message=None,
        body=body,
    )


def test_production_command_extracts_and_persists_page_facts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    body = b"<main>Family-owned since 1984. We offer a chapel.</main>"

    def fake_probe(url: str, **kwargs) -> HTTPProbeResult:
        del kwargs
        return _probe_result(url, body)

    monkeypatch.setattr(
        "canada_funeral_intel.business_intelligence.processing.probe_http",
        fake_probe,
    )

    with database_session(tmp_path / "production.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        entity_id, website_id, page_id = _seed(connection)

        result = run_business_facts_extract(
            connection,
            website_id=website_id,
            page_id=None,
            user_agent="Fixture/1.0",
            timeout_seconds=5,
            max_redirects=2,
        )
        rows = list_business_facts(connection, entity_id=entity_id)

    assert result["pages_selected"] == 1
    assert result["pages_attempted"] == 1
    assert result["pages_succeeded"] == 1
    assert result["pages_failed"] == 0
    assert result["facts_extracted"] == 3
    assert result["facts_inserted"] == 3
    assert result["facts_unchanged"] == 0
    assert {row["website_page_id"] for row in rows} == {page_id}
    assert {row["website_id"] for row in rows} == {website_id}
    assert {row["entity_id"] for row in rows} == {entity_id}
    assert {row["source_url"] for row in rows} == {"https://example.ca/team"}


def test_production_command_is_idempotent_and_preserves_changed_snapshots(
    monkeypatch,
    tmp_path: Path,
) -> None:
    bodies = [
        b"<main>Family-owned since 1984. Chapel available.</main>",
        b"<main>Family-owned since 1984. Chapel available.</main>",
        b"<main>Family-owned since 1985. Chapel available.</main>",
    ]
    calls = 0

    def fake_probe(url: str, **kwargs) -> HTTPProbeResult:
        nonlocal calls
        del kwargs
        body = bodies[min(calls, len(bodies) - 1)]
        calls += 1
        return _probe_result(url, body)

    monkeypatch.setattr(
        "canada_funeral_intel.business_intelligence.processing.probe_http",
        fake_probe,
    )

    with database_session(tmp_path / "history.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        entity_id, website_id, _ = _seed(connection)

        first = run_business_facts_extract(
            connection,
            website_id=website_id,
            page_id=None,
            user_agent="Fixture/1.0",
            timeout_seconds=5,
            max_redirects=2,
        )
        second = run_business_facts_extract(
            connection,
            website_id=website_id,
            page_id=None,
            user_agent="Fixture/1.0",
            timeout_seconds=5,
            max_redirects=2,
        )
        third = run_business_facts_extract(
            connection,
            website_id=website_id,
            page_id=None,
            user_agent="Fixture/1.0",
            timeout_seconds=5,
            max_redirects=2,
        )
        rows = list_business_facts(connection, entity_id=entity_id)

    assert first["facts_inserted"] == 3
    assert second["facts_inserted"] == 0
    assert second["facts_unchanged"] == 3
    assert third["facts_inserted"] == 3
    assert len(rows) == 6
    assert {row["fact_key"] for row in rows} == {
        "ownership_type",
        "founded_year",
        "service_offering",
    }
    assert len({row["content_hash"] for row in rows}) == 2


def test_production_command_is_page_fault_tolerant_and_uses_current_response(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with database_session(tmp_path / "failures.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        entity_id, website_id, first_page_id = _seed(connection)
        second_page_id = upsert_website_page(
            connection,
            DiscoveredPage(
                website_id=website_id,
                url="https://example.ca/about",
                normalized_url="https://example.ca/about",
                path="/about",
                page_kind="about",
                priority_score=84,
                depth=1,
                status_code=200,
                content_type="text/html",
            ),
        )
        connection.commit()

        def fake_probe(url: str, **kwargs) -> HTTPProbeResult:
            del kwargs
            if url.endswith("/team"):
                raise WebsiteProbeError("fixture timeout")
            return _probe_result(
                url,
                b"<main>Independent since 1999.</main>",
                status=503,
                content_type="text/html",
            )

        monkeypatch.setattr(
            "canada_funeral_intel.business_intelligence.processing.probe_http",
            fake_probe,
        )

        result = run_business_facts_extract(
            connection,
            website_id=website_id,
            page_id=None,
            user_agent="Fixture/1.0",
            timeout_seconds=5,
            max_redirects=2,
        )
        rows = list_business_facts(connection, entity_id=entity_id)

    assert result["pages_selected"] == 2
    assert result["pages_attempted"] == 2
    assert result["pages_succeeded"] == 1
    assert result["pages_failed"] == 1
    assert result["facts_extracted"] == 0
    assert result["facts_inserted"] == 0
    assert result["failures"] == [
        {
            "page_id": first_page_id,
            "website_id": website_id,
            "error": "fixture timeout",
        }
    ]
    assert rows == []
    assert second_page_id != first_page_id


def test_supported_business_pages_are_selected_but_generic_other_is_not(
    monkeypatch,
    tmp_path: Path,
) -> None:
    paths = ("services", "cremation", "pre-planning", "facilities", "chapel")
    with database_session(tmp_path / "business-pages.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        entity_id, website_id, _ = _seed(connection)
        page_ids: dict[str, int] = {}
        for index, name in enumerate((*paths, "news")):
            url = f"https://example.ca/{name}"
            page_kind, priority = classify_page(url)
            page_ids[name] = upsert_website_page(
                connection,
                DiscoveredPage(
                    website_id=website_id,
                    url=url,
                    normalized_url=url,
                    path=f"/{name}",
                    page_kind=page_kind,
                    priority_score=priority,
                    depth=index + 1,
                    status_code=503,
                    content_type="application/octet-stream",
                ),
            )
        connection.commit()

        probed: list[str] = []

        def fake_probe(url: str, **kwargs) -> HTTPProbeResult:
            del kwargs
            probed.append(url)
            return _probe_result(
                url,
                b"<main>We offer chapel, cremation and pre-planning services.</main>",
            )

        monkeypatch.setattr(
            "canada_funeral_intel.business_intelligence.processing.probe_http",
            fake_probe,
        )
        result = run_business_facts_extract(
            connection,
            website_id=website_id,
            page_id=None,
            user_agent="Fixture/1.0",
            timeout_seconds=5,
            max_redirects=2,
        )
        rows = list_business_facts(connection, entity_id=entity_id)

    expected_urls = {f"https://example.ca/{name}" for name in paths}
    assert result["pages_selected"] == len(paths) + 1
    assert set(probed) == expected_urls | {"https://example.ca/team"}
    assert "https://example.ca/news" not in probed
    assert page_ids["news"] not in {row["website_page_id"] for row in rows}


def test_production_command_empty_and_non_html_responses_are_no_fact_successes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with database_session(tmp_path / "responses.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        _, website_id, first_page_id = _seed(connection)
        second_page_id = upsert_website_page(
            connection,
            DiscoveredPage(
                website_id=website_id,
                url="https://example.ca/contact",
                normalized_url="https://example.ca/contact",
                path="/contact",
                page_kind="contact",
                priority_score=78,
                depth=1,
                status_code=200,
                content_type="text/html",
            ),
        )
        connection.commit()

        def fake_probe(url: str, **kwargs) -> HTTPProbeResult:
            del kwargs
            if url.endswith("/team"):
                return _probe_result(url, b"", content_type="text/html")
            return _probe_result(url, b"not html", content_type="application/pdf")

        monkeypatch.setattr(
            "canada_funeral_intel.business_intelligence.processing.probe_http",
            fake_probe,
        )

        result = run_business_facts_extract(
            connection,
            website_id=website_id,
            page_id=None,
            user_agent="Fixture/1.0",
            timeout_seconds=5,
            max_redirects=2,
        )

    assert result["pages_selected"] == 2
    assert result["pages_succeeded"] == 2
    assert result["pages_failed"] == 0
    assert result["facts_extracted"] == 0
    assert first_page_id != second_page_id


def test_business_fact_read_commands_do_not_retrieve_pages(
    monkeypatch,
    tmp_path: Path,
) -> None:
    def unexpected_probe(*args, **kwargs):
        del args, kwargs
        raise AssertionError("read-only business-fact command performed network I/O")

    monkeypatch.setattr(
        "canada_funeral_intel.business_intelligence.processing.probe_http",
        unexpected_probe,
    )

    with database_session(tmp_path / "read-only.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        assert run_business_facts_list(connection) == []
        assert run_business_facts_summary(connection) == []
        result = run_business_facts_export(connection, output=tmp_path / "export")

    assert result["files"] == [
        "business_facts.csv",
        "business_fact_summary.csv",
    ]


def test_main_extract_without_selector_returns_command_error_and_does_not_probe(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    def unexpected_probe(*args, **kwargs):
        del args, kwargs
        raise AssertionError("selector validation attempted network I/O")

    monkeypatch.setattr(
        "canada_funeral_intel.business_intelligence.processing.probe_http",
        unexpected_probe,
    )
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "no-selector.sqlite3"))

    result = main(["business-facts", "extract"])
    captured = capsys.readouterr()

    assert result == 18
    assert "website_id or page_id is required" in captured.err
    assert captured.out == ""


def test_main_extract_page_id_processes_only_selected_page(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    database_path = tmp_path / "page-selector.sqlite3"
    with database_session(database_path) as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        entity_id, website_id, page_id = _seed(connection)
        unrelated_page_id = upsert_website_page(
            connection,
            DiscoveredPage(
                website_id=website_id,
                url="https://example.ca/about",
                normalized_url="https://example.ca/about",
                path="/about",
                page_kind="about",
                priority_score=84,
                depth=1,
                status_code=200,
                content_type="text/html",
            ),
        )
        connection.commit()

    probed: list[str] = []

    def fake_probe(url: str, **kwargs) -> HTTPProbeResult:
        del kwargs
        probed.append(url)
        return _probe_result(url, b"<main>Family-owned since 1984.</main>")

    monkeypatch.setattr(
        "canada_funeral_intel.business_intelligence.processing.probe_http",
        fake_probe,
    )
    monkeypatch.setenv("DATABASE_PATH", str(database_path))

    result = main(["business-facts", "extract", "--page-id", str(page_id)])
    payload = json.loads(capsys.readouterr().out)

    assert result == 0
    assert payload["pages_selected"] == 1
    assert probed == ["https://example.ca/team"]
    with database_session(database_path) as connection:
        rows = list_business_facts(connection, entity_id=entity_id)
    assert unrelated_page_id not in {row["website_page_id"] for row in rows}
    assert payload["facts_inserted"] == 2


def test_main_extract_mismatched_website_and_page_selects_zero_rows(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    database_path = tmp_path / "mismatched-selector.sqlite3"
    with database_session(database_path) as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        _, website_a, _ = _seed(connection, name="Website A")
        _, website_b, page_b = _seed(connection, name="Website B")
        connection.commit()

    monkeypatch.setattr(
        "canada_funeral_intel.business_intelligence.processing.probe_http",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("mismatched selectors should select no pages")
        ),
    )
    monkeypatch.setenv("DATABASE_PATH", str(database_path))

    result = main(
        [
            "business-facts",
            "extract",
            "--website-id",
            str(website_a),
            "--page-id",
            str(page_b),
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert result == 0
    assert payload["pages_selected"] == 0
    assert payload["pages_attempted"] == 0
    assert website_b != website_a


@pytest.mark.parametrize("selector", ["--website-id", "--page-id"])
def test_main_extract_rejects_zero_selector_values(
    monkeypatch,
    tmp_path: Path,
    capsys,
    selector: str,
) -> None:
    monkeypatch.setattr(
        "canada_funeral_intel.business_intelligence.processing.probe_http",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("invalid selector should not probe")
        ),
    )
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / f"invalid-{selector}.sqlite3"))

    result = main(["business-facts", "extract", selector, "0"])
    captured = capsys.readouterr()

    assert result == 18
    expected_name = selector.removeprefix("--").replace("-", "_")
    assert f"{expected_name} must be positive" in captured.err


def test_final_probe_url_is_retained_as_fact_source_url(
    monkeypatch,
    tmp_path: Path,
) -> None:
    final_url = "https://redirected.example/about"

    def fake_probe(url: str, **kwargs) -> HTTPProbeResult:
        del kwargs
        result = _probe_result(url, b"<main>Independent since 1999.</main>")
        return HTTPProbeResult(
            requested_url=result.requested_url,
            final_url=final_url,
            status_code=result.status_code,
            redirect_count=1,
            response_time_ms=result.response_time_ms,
            content_type=result.content_type,
            canonical_url=None,
            error_message=None,
            body=result.body,
        )

    monkeypatch.setattr(
        "canada_funeral_intel.business_intelligence.processing.probe_http",
        fake_probe,
    )

    with database_session(tmp_path / "redirect.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        entity_id, website_id, _ = _seed(connection)
        run_business_facts_extract(
            connection,
            website_id=website_id,
            page_id=None,
            user_agent="Fixture/1.0",
            timeout_seconds=5,
            max_redirects=2,
        )
        rows = list_business_facts(connection, entity_id=entity_id)

    assert {row["source_url"] for row in rows} == {final_url}


def test_page_processing_order_matches_page_query_order(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with database_session(tmp_path / "ordering.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        _, website_a, first_page_id = _seed(connection, name="Website A")
        upsert_website_page(
            connection,
            DiscoveredPage(
                website_id=website_a,
                url="https://example.ca/about",
                normalized_url="https://example.ca/about",
                path="/about",
                page_kind="about",
                priority_score=99,
                depth=0,
            ),
        )
        upsert_website_page(
            connection,
            DiscoveredPage(
                website_id=website_a,
                url="https://example.ca/contact",
                normalized_url="https://example.ca/contact",
                path="/contact",
                page_kind="contact",
                priority_score=50,
                depth=2,
            ),
        )
        _, website_b, unrelated_page_id = _seed(connection, name="Website B")
        connection.execute(
            "UPDATE website_pages SET priority_score = 1, depth = 7 WHERE id = ?",
            (first_page_id,),
        )
        connection.execute(
            "UPDATE website_pages SET priority_score = 2, depth = 1 WHERE id = ?",
            (unrelated_page_id,),
        )
        connection.commit()

        probed: list[str] = []

        def fake_probe(url: str, **kwargs) -> HTTPProbeResult:
            del kwargs
            probed.append(url)
            return _probe_result(url, b"<main></main>")

        monkeypatch.setattr(
            "canada_funeral_intel.business_intelligence.processing.probe_http",
            fake_probe,
        )
        result = run_business_facts_extract(
            connection,
            website_id=website_a,
            page_id=None,
            user_agent="Fixture/1.0",
            timeout_seconds=5,
            max_redirects=2,
        )

    assert result["pages_selected"] == 3
    assert probed == [
        "https://example.ca/about",
        "https://example.ca/contact",
        "https://example.ca/team",
    ]
    assert website_b > website_a


def test_fatal_storage_error_is_not_reported_as_page_failure(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    database_path = tmp_path / "storage-error.sqlite3"
    with database_session(database_path) as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        _, _, page_id = _seed(connection)

    monkeypatch.setattr(
        "canada_funeral_intel.business_intelligence.processing.probe_http",
        lambda url, **kwargs: _probe_result(
            url, b"<main>Family-owned since 1984.</main>"
        ),
    )
    monkeypatch.setattr(
        "canada_funeral_intel.business_intelligence.processing.store_business_facts",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            sqlite3.IntegrityError("fixture integrity failure")
        ),
    )
    monkeypatch.setenv("DATABASE_PATH", str(database_path))

    result = main(["business-facts", "extract", "--page-id", str(page_id)])
    captured = capsys.readouterr()

    assert result == 18
    assert "fixture integrity failure" in captured.err
    assert "pages_failed" not in captured.err


def test_website_crawl_does_not_invoke_business_fact_processing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with database_session(tmp_path / "crawl-boundary.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        _, website_id, _ = _seed(connection)

        def fake_crawl_probe(url: str, **kwargs) -> HTTPProbeResult:
            del kwargs
            return _probe_result(url, b"<html><body>Home</body></html>")

        monkeypatch.setattr(
            "canada_funeral_intel.verification.page_discovery.probe_http",
            fake_crawl_probe,
        )
        monkeypatch.setattr(
            "canada_funeral_intel.business_intelligence.processing.extract_business_facts_from_pages",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("crawler invoked business-fact processing")
            ),
        )

        result = discover_website_pages(
            connection,
            website_id=website_id,
            user_agent="Fixture/1.0",
            timeout_seconds=5,
            max_redirects=2,
            max_pages=1,
            max_depth=0,
        )

    assert result.pages_persisted == 1


def test_offline_pipeline_does_not_invoke_business_fact_processing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "pipeline-boundary.sqlite3"
    input_path = tmp_path / "records.json"
    input_path.write_text(
        json.dumps([{"id": "a", "name": "Alpha Funeral Home"}]),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "canada_funeral_intel.business_intelligence.processing.extract_business_facts_from_pages",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("offline pipeline invoked business-fact processing")
        ),
    )

    with database_session(database_path) as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        connection.execute(
            "INSERT INTO source_datasets (id, name, source_type, jurisdiction) VALUES (1, 'Fixture', 'manual', 'CA')"
        )
        connection.commit()
        result = create_run(
            connection,
            PipelineInput(
                source_dataset_id=1,
                input_path=input_path,
                input_format=ImportFormat.JSON,
                external_id_field="id",
            ),
        )

    assert result["status"] == "completed"
