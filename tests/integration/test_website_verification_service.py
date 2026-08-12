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
from canada_funeral_intel.verification.website_cli import (
    run_website_checks,
    run_website_verify,
)

ROOT = Path(__file__).resolve().parents[2]
MIGRATION_DIR = ROOT / "database" / "migrations"


def _seed_website(connection) -> int:
    cursor = connection.execute(
        """
        INSERT INTO entities (entity_type, canonical_name)
        VALUES ('organization', 'Phase 6B Fixture')
        """
    )
    assert cursor.lastrowid is not None
    entity_id = int(cursor.lastrowid)
    connection.commit()

    candidate = make_website_candidate(
        entity_id=entity_id,
        url="https://example.ca/",
        discovery_method="manual",
        confidence=0.8,
    )
    return upsert_website_candidate(connection, candidate).website_id


def test_verify_service_persists_completed_probe(monkeypatch, tmp_path: Path) -> None:
    database_path = tmp_path / "verify.sqlite3"

    with database_session(database_path) as connection:
        apply_pending_migrations(connection, MIGRATION_DIR)
        website_id = _seed_website(connection)

        monkeypatch.setattr(
            "canada_funeral_intel.verification.website_cli.probe_website",
            lambda **kwargs: WebsiteCheck(
                website_id=website_id,
                requested_url="https://example.ca/",
                final_url="https://www.example.ca/",
                dns_status=DNSStatus.OK,
                dns_addresses=("203.0.113.20",),
                tls_status=TLSStatus.OK,
                https_status_code=200,
                http_status_code=301,
                redirect_count=1,
                response_time_ms=80,
                content_type="text/html",
                canonical_url="https://www.example.ca/",
                outcome=WebsiteCheckOutcome.REACHABLE,
            ),
        )

        payload = run_website_verify(
            connection,
            website_id=website_id,
            user_agent="Test/1.0",
            timeout_seconds=5,
            max_redirects=3,
        )

        assert payload["website_id"] == website_id
        assert payload["outcome"] == "reachable"
        assert payload["https_status_code"] == 200
        assert payload["http_status_code"] == 301
        assert payload["check_id"] > 0


def test_verify_service_appends_history(monkeypatch, tmp_path: Path) -> None:
    database_path = tmp_path / "history.sqlite3"

    with database_session(database_path) as connection:
        apply_pending_migrations(connection, MIGRATION_DIR)
        website_id = _seed_website(connection)

        monkeypatch.setattr(
            "canada_funeral_intel.verification.website_cli.probe_website",
            lambda **kwargs: WebsiteCheck(
                website_id=website_id,
                requested_url="https://example.ca/",
                dns_status=DNSStatus.OK,
                dns_addresses=("203.0.113.30",),
                tls_status=TLSStatus.FAILED,
                http_status_code=200,
                outcome=WebsiteCheckOutcome.REACHABLE,
            ),
        )

        first = run_website_verify(
            connection,
            website_id=website_id,
            user_agent="Test/1.0",
            timeout_seconds=5,
            max_redirects=3,
        )
        second = run_website_verify(
            connection,
            website_id=website_id,
            user_agent="Test/1.0",
            timeout_seconds=5,
            max_redirects=3,
        )
        history = run_website_checks(
            connection,
            website_id=website_id,
        )

        assert first["check_id"] != second["check_id"]
        assert len(history) == 2
