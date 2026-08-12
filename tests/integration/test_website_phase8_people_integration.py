from pathlib import Path

from canada_funeral_intel.extraction.page_people import extract_website_people
from canada_funeral_intel.extraction.storage import list_page_person_observations
from canada_funeral_intel.storage.database import database_session
from canada_funeral_intel.storage.migrations import apply_pending_migrations
from canada_funeral_intel.verification.models import WebsiteKind, WebsiteStatus
from canada_funeral_intel.verification.page_discovery import (
    DiscoveredPage,
    upsert_website_page,
)
from canada_funeral_intel.verification.probe import HTTPProbeResult
from canada_funeral_intel.verification.storage import (
    make_website_candidate,
    queue_website_for_review,
    upsert_website_candidate,
)

MIGRATION_DIR = Path(__file__).resolve().parents[2] / "database" / "migrations"


def _seed(connection, *, name: str = "Prairie Rose Funeral Home") -> tuple[int, int, int]:
    entity = connection.execute(
        """
        INSERT INTO entities (entity_type, canonical_name)
        VALUES ('organization', ?)
        """,
        (name,),
    )
    entity_id = int(entity.lastrowid)
    connection.commit()
    website_id = upsert_website_candidate(
        connection,
        make_website_candidate(
            entity_id=entity_id,
            url="https://example.ca/",
            discovery_method="manual",
            confidence=0.9,
            website_kind=WebsiteKind.SHARED,
            status=WebsiteStatus.REVIEW,
        ),
    ).website_id
    queue_website_for_review(connection, website_id)
    page_id = upsert_website_page(
        connection,
        DiscoveredPage(
            website_id=website_id,
            url="https://example.ca/team",
            normalized_url="https://example.ca/team",
            path="/team",
            page_kind="team",
            priority_score=95,
            depth=1,
            status_code=200,
            content_type="text/html",
            identity_score=1.0,
            identity_observable=True,
        ),
    )
    connection.commit()
    return entity_id, website_id, page_id


def test_phase8_extracts_and_preserves_historical_snapshots(monkeypatch, tmp_path: Path) -> None:
    bodies = [
        b"""
        <html><body><div class="team-card">
          <h2>Alice Smith</h2><p>Funeral Director</p>
          <a href="mailto:alice@example.ca">alice@example.ca</a>
          <span>403-555-0100</span>
        </div></body></html>
        """,
        b"""
        <html><body><div class="team-card">
          <h2>Alice Smith</h2><p>Funeral Director</p>
          <a href="mailto:alice@example.ca">alice@example.ca</a>
          <span>403-555-0100</span>
        </div></body></html>
        """,
        b"""
        <html><body><div class="team-card">
          <h2>Alice Smith</h2><p>Managing Funeral Director</p>
          <a href="mailto:alice@example.ca">alice@example.ca</a>
          <span>403-555-0100</span>
        </div></body></html>
        """,
    ]
    calls = 0

    def fake_probe(url: str, **kwargs) -> HTTPProbeResult:
        nonlocal calls
        del url, kwargs
        body = bodies[min(calls, len(bodies) - 1)]
        calls += 1
        return HTTPProbeResult(
            requested_url="https://example.ca/team",
            final_url="https://example.ca/team",
            status_code=200,
            redirect_count=0,
            response_time_ms=1,
            content_type="text/html",
            canonical_url=None,
            error_message=None,
            body=body,
        )

    monkeypatch.setattr(
        "canada_funeral_intel.extraction.page_people.probe_http",
        fake_probe,
    )

    with database_session(tmp_path / "people.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATION_DIR)
        entity_id, website_id, page_id = _seed(connection)

        first = extract_website_people(
            connection,
            website_id=website_id,
            user_agent="Fixture/1.0",
            timeout_seconds=5,
            max_redirects=2,
        )
        second = extract_website_people(
            connection,
            website_id=website_id,
            user_agent="Fixture/1.0",
            timeout_seconds=5,
            max_redirects=2,
        )
        third = extract_website_people(
            connection,
            website_id=website_id,
            user_agent="Fixture/1.0",
            timeout_seconds=5,
            max_redirects=2,
        )

        assert first.observations_inserted == 1
        assert second.observations_inserted == 0
        assert second.observations_unchanged == 1
        assert third.observations_inserted == 1
        rows = list_page_person_observations(connection, entity_id=entity_id)
        assert len(rows) == 2
        assert {row["website_page_id"] for row in rows} == {page_id}
        assert {row["entity_id"] for row in rows} == {entity_id}
        assert len({row["content_hash"] for row in rows}) == 2

        website = connection.execute(
            "SELECT website_kind, status, is_primary FROM websites WHERE id = ?",
            (website_id,),
        ).fetchone()
        queue = connection.execute(
            "SELECT status FROM website_review_queue WHERE website_id = ?",
            (website_id,),
        ).fetchone()
        assert tuple(website) == ("shared", "review", 0)
        assert queue["status"] == "pending"


def test_phase8_skips_ineligible_pages_and_keeps_branch_context_observational(
    monkeypatch,
    tmp_path: Path,
) -> None:
    def fake_probe(url: str, **kwargs) -> HTTPProbeResult:
        del url, kwargs
        return HTTPProbeResult(
            requested_url="https://example.ca/team",
            final_url="https://example.ca/team",
            status_code=200,
            redirect_count=0,
            response_time_ms=1,
            content_type="text/html",
            canonical_url=None,
            error_message=None,
            body=b"<div><h2>Branch Person</h2><p>Owner</p></div>",
        )

    monkeypatch.setattr(
        "canada_funeral_intel.extraction.page_people.probe_http",
        fake_probe,
    )

    with database_session(tmp_path / "eligibility.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATION_DIR)
        _, website_id, page_id = _seed(connection)
        connection.execute(
            """
            UPDATE website_pages
            SET identity_observable = 0, identity_score = NULL
            WHERE id = ?
            """,
            (page_id,),
        )
        connection.commit()

        result = extract_website_people(
            connection,
            website_id=website_id,
            user_agent="Fixture/1.0",
            timeout_seconds=5,
            max_redirects=2,
        )
        assert result.pages_fetched == 0
        assert result.skip_reasons["identity_not_observable"] == 1
        assert list_page_person_observations(connection, website_id=website_id) == ()


def test_phase8_cli_listing_is_deterministic(tmp_path: Path) -> None:
    from canada_funeral_intel.verification.website_cli import run_website_people

    with database_session(tmp_path / "cli.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATION_DIR)
        _, website_id, _ = _seed(connection)
        assert run_website_people(
            connection, website_id=website_id, entity_id=None, page_id=None
        ) == []


def test_phase8_rejects_soft404_parked_non_success_and_non_html_responses(
    monkeypatch,
    tmp_path: Path,
) -> None:
    responses = {
        "https://example.ca/team": (200, "text/html", b"<p>Page not found</p>"),
        "https://example.ca/parked": (200, "text/html", b"This domain is for sale"),
        "https://example.ca/error": (503, "text/html", b"<p>Owner Alice Smith</p>"),
        "https://example.ca/feed": (200, "application/json", b"{}"),
    }

    def fake_probe(url: str, **kwargs) -> HTTPProbeResult:
        del kwargs
        status, content_type, body = responses[url]
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

    monkeypatch.setattr(
        "canada_funeral_intel.extraction.page_people.probe_http",
        fake_probe,
    )

    with database_session(tmp_path / "rejections.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATION_DIR)
        _, website_id, _ = _seed(connection)
        for url in (
            "https://example.ca/parked",
            "https://example.ca/error",
            "https://example.ca/feed",
        ):
            upsert_website_page(
                connection,
                DiscoveredPage(
                    website_id=website_id,
                    url=url,
                    normalized_url=url,
                    path=url.removeprefix("https://example.ca"),
                    page_kind="team",
                    priority_score=95,
                    depth=1,
                    status_code=200,
                    content_type="text/html",
                    identity_score=1.0,
                    identity_observable=True,
                ),
            )
        connection.commit()

        result = extract_website_people(
            connection,
            website_id=website_id,
            user_agent="Fixture/1.0",
            timeout_seconds=5,
            max_redirects=2,
        )
        assert result.observations_inserted == 0
        assert result.skip_reasons["excluded_content"] == 2
        assert result.skip_reasons["non_success"] == 1
        assert result.skip_reasons["non_html"] == 1
        assert list_page_person_observations(connection, website_id=website_id) == ()
