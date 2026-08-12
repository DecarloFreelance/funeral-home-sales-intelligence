from pathlib import Path

from canada_funeral_intel.storage.database import database_session
from canada_funeral_intel.storage.migrations import apply_pending_migrations
from canada_funeral_intel.verification.models import (
    WebsiteKind,
    WebsiteReviewStatus,
    WebsiteStatus,
)
from canada_funeral_intel.verification.page_discovery import (
    discover_website_pages,
    list_website_pages,
)
from canada_funeral_intel.verification.probe import HTTPProbeResult
from canada_funeral_intel.verification.review import list_website_review_queue
from canada_funeral_intel.verification.storage import (
    make_website_candidate,
    queue_website_for_review,
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


def test_phase7_page_identity_is_observation_only(
    monkeypatch,
    tmp_path: Path,
) -> None:
    bodies = {
        "https://example.ca/": b"""
            <html><body>
              <a href="/locations/edmonton">Edmonton</a>
              <a href="/soft">Soft</a>
              <a href="/parked">Parked</a>
              <a href="/error">Error</a>
            </body></html>
        """,
        "https://example.ca/locations/edmonton": (
            b"<html><body>Prairie Rose Funeral Home Edmonton</body></html>"
        ),
        "https://example.ca/soft": b"<html><body>Page not found</body></html>",
        "https://example.ca/parked": b"<html><body>This domain is for sale</body></html>",
        "https://example.ca/error": b"<html><body>Prairie Rose Funeral Home</body></html>",
    }
    statuses = {"https://example.ca/error": 503}

    def fake_probe_http(url: str, **kwargs) -> HTTPProbeResult:
        del kwargs
        return HTTPProbeResult(
            requested_url=url,
            final_url=url,
            status_code=statuses.get(url, 200),
            redirect_count=0,
            response_time_ms=5,
            content_type="text/html",
            canonical_url=None,
            error_message=None,
            body=bodies[url],
        )

    monkeypatch.setattr(
        "canada_funeral_intel.verification.page_discovery.probe_http",
        fake_probe_http,
    )

    with database_session(tmp_path / "identity.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATION_DIR)
        cursor = connection.execute(
            """
            INSERT INTO entities (entity_type, canonical_name)
            VALUES ('organization', 'Prairie Rose Funeral Home')
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
                website_kind=WebsiteKind.SHARED,
                status=WebsiteStatus.REVIEW,
            ),
        ).website_id
        queue_website_for_review(connection, website_id=website_id)

        result = discover_website_pages(
            connection,
            website_id=website_id,
            user_agent="Test/1.0",
            timeout_seconds=5,
            max_redirects=3,
            max_pages=5,
            max_depth=1,
        )

        assert result.pages_requested == 5
        rows = {
            row["path"]: row
            for row in list_website_pages(connection, website_id=website_id)
        }
        assert rows["/"]["identity_observable"] is True
        assert rows["/"]["identity_score"] == 0.0
        assert rows["/locations/edmonton"]["identity_observable"] is True
        assert rows["/locations/edmonton"]["identity_score"] == 1.0
        assert rows["/soft"]["identity_observable"] is False
        assert rows["/soft"]["identity_score"] is None
        assert rows["/parked"]["identity_observable"] is False
        assert rows["/parked"]["identity_score"] is None
        assert rows["/error"]["identity_observable"] is False
        assert rows["/error"]["identity_score"] is None

        website = connection.execute(
            "SELECT website_kind, status, is_primary FROM websites WHERE id = ?",
            (website_id,),
        ).fetchone()
        assert tuple(website) == ("shared", "review", 0)
        queue = list_website_review_queue(connection)
        assert len(queue) == 1
        assert queue[0].review_status is WebsiteReviewStatus.PENDING
