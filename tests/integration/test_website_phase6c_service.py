from __future__ import annotations

from pathlib import Path

from canada_funeral_intel.storage import database_session
from canada_funeral_intel.storage.migrations import apply_pending_migrations
from canada_funeral_intel.verification.checks import (
    DNSStatus,
    TLSStatus,
    WebsiteCheck,
    WebsiteCheckOutcome,
)
from canada_funeral_intel.verification.storage import (
    make_website_candidate,
    upsert_website_candidate,
)
from canada_funeral_intel.verification.website_cli import run_website_verify

ROOT = Path(__file__).resolve().parents[2]
MIGRATION_DIR = ROOT / "database" / "migrations"


def test_verify_service_passes_entity_name_to_probe(
    monkeypatch, tmp_path: Path
) -> None:
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
                url="https://prairierose.example/",
                discovery_method="manual",
                confidence=0.8,
            ),
        ).website_id

        captured: dict[str, object] = {}

        def fake_probe(**kwargs):
            captured.update(kwargs)
            return WebsiteCheck(
                website_id=website_id,
                requested_url="https://prairierose.example/",
                dns_status=DNSStatus.OK,
                tls_status=TLSStatus.OK,
                https_status_code=200,
                identity_score=1.0,
                outcome=WebsiteCheckOutcome.REACHABLE,
            )

        monkeypatch.setattr(
            "canada_funeral_intel.verification.website_cli.probe_website",
            fake_probe,
        )

        run_website_verify(
            connection,
            website_id=website_id,
            user_agent="Test/1.0",
            timeout_seconds=5,
            max_redirects=3,
        )

        assert captured["expected_business_name"] == "Prairie Rose Funeral Home"
