from pathlib import Path

from canada_funeral_intel.storage.database import database_session
from canada_funeral_intel.storage.migrations import apply_pending_migrations
from canada_funeral_intel.verification.page_discovery import (
    DiscoveredPage,
    list_website_pages,
    upsert_website_page,
)
from canada_funeral_intel.verification.storage import (
    make_website_candidate,
    upsert_website_candidate,
)

MIGRATION_DIR = Path(__file__).resolve().parents[2] / "database" / "migrations"


def test_phase7_page_schema_and_storage(tmp_path: Path) -> None:
    with database_session(tmp_path / "phase7.sqlite3") as connection:
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
                'Prairie Rose Funeral Home'
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
                url="https://prairierose.example/",
                discovery_method="manual",
                confidence=0.9,
            ),
        ).website_id

        page_id = upsert_website_page(
            connection,
            DiscoveredPage(
                website_id=website_id,
                url=("https://prairierose.example/about/our-team"),
                normalized_url=("https://prairierose.example/about/our-team"),
                path="/about/our-team",
                page_kind="team",
                priority_score=95,
                depth=1,
                discovered_from_url=("https://prairierose.example/"),
                link_text="Our Team",
                status_code=200,
                content_type="text/html",
            ),
        )

        assert page_id > 0

        rows = list_website_pages(
            connection,
            website_id=website_id,
        )

        assert len(rows) == 1
        assert rows[0]["website_id"] == website_id
        assert rows[0]["page_kind"] == "team"
        assert rows[0]["priority_score"] == 95
        assert rows[0]["depth"] == 1
