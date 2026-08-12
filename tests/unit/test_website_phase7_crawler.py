from pathlib import Path

from canada_funeral_intel.storage.database import database_session
from canada_funeral_intel.storage.migrations import apply_pending_migrations
from canada_funeral_intel.verification.page_discovery import (
    discover_website_pages,
    list_website_pages,
)
from canada_funeral_intel.verification.probe import HTTPProbeResult
from canada_funeral_intel.verification.storage import (
    make_website_candidate,
    upsert_website_candidate,
)

MIGRATION_DIR = Path(__file__).resolve().parents[2] / "database" / "migrations"


def test_phase7_crawler_is_bounded_same_site_and_prioritized(
    monkeypatch,
    tmp_path: Path,
) -> None:
    bodies = {
        "https://example.ca/": b"""
            <html><body>
              <a href="/obituaries">Obituaries</a>
              <a href="/generic">Generic</a>
              <a href="/about/our-team">Our Team</a>
              <a href="https://outside.example/team">
                Outside Team
              </a>
            </body></html>
        """,
        "https://example.ca/about/our-team": (b"<html><body>Team page</body></html>"),
        "https://example.ca/generic": (b"<html><body>Generic page</body></html>"),
    }

    requested: list[str] = []

    def fake_probe_http(
        url: str,
        **kwargs,
    ) -> HTTPProbeResult:
        del kwargs
        requested.append(url)
        return HTTPProbeResult(
            requested_url=url,
            final_url=url,
            status_code=200,
            redirect_count=0,
            response_time_ms=5,
            content_type="text/html",
            canonical_url=None,
            error_message=None,
            body=bodies.get(
                url,
                b"<html><body></body></html>",
            ),
        )

    monkeypatch.setattr(
        "canada_funeral_intel.verification.page_discovery.probe_http",
        fake_probe_http,
    )

    with database_session(tmp_path / "crawl.sqlite3") as connection:
        apply_pending_migrations(
            connection,
            MIGRATION_DIR,
        )

        cursor = connection.execute(
            """
            INSERT INTO entities (
                entity_type,
                canonical_name
            )
            VALUES (
                'organization',
                'Example Funeral Home'
            )
            """
        )
        assert cursor.lastrowid is not None
        entity_id = int(cursor.lastrowid)
        connection.commit()

        website_id = upsert_website_candidate(
            connection,
            make_website_candidate(
                entity_id=entity_id,
                url="https://example.ca/",
                discovery_method="manual",
                confidence=0.9,
            ),
        ).website_id

        result = discover_website_pages(
            connection,
            website_id=website_id,
            user_agent="Test/1.0",
            timeout_seconds=5,
            max_redirects=3,
            max_pages=2,
            max_depth=2,
        )

        assert result.pages_requested == 2
        assert result.excluded_links == 1
        assert result.offsite_links == 1

        assert requested == [
            "https://example.ca/",
            "https://example.ca/about/our-team",
        ]

        rows = list_website_pages(
            connection,
            website_id=website_id,
        )

        assert len(rows) == 2
        assert rows[0]["page_kind"] == "team"
