from __future__ import annotations

from pathlib import Path

from canada_funeral_intel.storage import database_session
from canada_funeral_intel.storage.migrations import (
    apply_pending_migrations,
)
from canada_funeral_intel.verification.checks import (
    DNSStatus,
    TLSStatus,
    WebsiteCheck,
    WebsiteCheckOutcome,
    insert_website_check,
    list_website_checks,
)
from canada_funeral_intel.verification.storage import (
    make_website_candidate,
    upsert_website_candidate,
)

ROOT = Path(__file__).resolve().parents[2]
MIGRATION_DIR = ROOT / "database" / "migrations"


def _seed_website(connection) -> int:
    cursor = connection.execute(
        """
        INSERT INTO entities (
            entity_type,
            canonical_name
        )
        VALUES (
            'organization',
            'Phase 6 Fixture'
        )
        """
    )

    assert cursor.lastrowid is not None
    entity_id = int(cursor.lastrowid)

    connection.commit()

    candidate = make_website_candidate(
        entity_id=entity_id,
        url="https://example.ca/",
        discovery_method="manual",
        confidence=0.80,
    )

    return upsert_website_candidate(
        connection,
        candidate,
    ).website_id


def test_website_checks_schema_exists(tmp_path: Path) -> None:
    with database_session(tmp_path / "schema.sqlite3") as connection:
        result = apply_pending_migrations(
            connection,
            MIGRATION_DIR,
        )

        assert result.status.current_version == 27

        columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(website_checks)"
            ).fetchall()
        }

        assert {
            "id",
            "website_id",
            "requested_url",
            "final_url",
            "dns_status",
            "dns_addresses",
            "tls_status",
            "tls_expires_at",
            "https_status_code",
            "http_status_code",
            "redirect_count",
            "response_time_ms",
            "content_type",
            "canonical_url",
            "soft_404",
            "parked_or_for_sale",
            "identity_score",
            "outcome",
            "error_message",
            "checked_at",
        } == columns


def test_website_check_history_preserves_multiple_runs(
    tmp_path: Path,
) -> None:
    with database_session(tmp_path / "history.sqlite3") as connection:
        apply_pending_migrations(
            connection,
            MIGRATION_DIR,
        )

        website_id = _seed_website(connection)

        first_id = insert_website_check(
            connection,
            WebsiteCheck(
                website_id=website_id,
                requested_url="https://example.ca/",
                dns_status=DNSStatus.FAILED,
                tls_status=TLSStatus.NOT_CHECKED,
                outcome=WebsiteCheckOutcome.UNREACHABLE,
                error_message="DNS resolution failed",
            ),
        )

        second_id = insert_website_check(
            connection,
            WebsiteCheck(
                website_id=website_id,
                requested_url="https://example.ca/",
                final_url="https://www.example.ca/",
                dns_status=DNSStatus.OK,
                dns_addresses=("192.0.2.20",),
                tls_status=TLSStatus.OK,
                https_status_code=200,
                redirect_count=1,
                response_time_ms=150,
                content_type="text/html; charset=utf-8",
                canonical_url="https://www.example.ca/",
                identity_score=0.95,
                outcome=WebsiteCheckOutcome.REACHABLE,
            ),
        )

        assert first_id != second_id

        rows = list_website_checks(
            connection,
            website_id=website_id,
        )

        assert len(rows) == 2
        assert {row.check_id for row in rows} == {
            first_id,
            second_id,
        }


def test_website_check_round_trip_preserves_fields(
    tmp_path: Path,
) -> None:
    with database_session(tmp_path / "round-trip.sqlite3") as connection:
        apply_pending_migrations(
            connection,
            MIGRATION_DIR,
        )

        website_id = _seed_website(connection)

        check_id = insert_website_check(
            connection,
            WebsiteCheck(
                website_id=website_id,
                requested_url="https://example.ca/",
                final_url="https://example.ca/home",
                dns_status=DNSStatus.OK,
                dns_addresses=(
                    "192.0.2.25",
                    "2001:db8::25",
                ),
                tls_status=TLSStatus.OK,
                tls_expires_at="2027-08-01T00:00:00Z",
                https_status_code=200,
                http_status_code=301,
                redirect_count=2,
                response_time_ms=243,
                content_type="text/html",
                canonical_url="https://example.ca/",
                soft_404=False,
                parked_or_for_sale=False,
                identity_score=0.88,
                outcome=WebsiteCheckOutcome.REACHABLE,
            ),
        )

        rows = list_website_checks(
            connection,
            website_id=website_id,
        )

        assert len(rows) == 1

        row = rows[0]

        assert row.check_id == check_id
        assert row.website_id == website_id
        assert row.dns_status is DNSStatus.OK
        assert row.dns_addresses == (
            "192.0.2.25",
            "2001:db8::25",
        )
        assert row.tls_status is TLSStatus.OK
        assert row.https_status_code == 200
        assert row.http_status_code == 301
        assert row.redirect_count == 2
        assert row.response_time_ms == 243
        assert row.content_type == "text/html"
        assert row.identity_score == 0.88
        assert row.outcome is WebsiteCheckOutcome.REACHABLE
        assert row.checked_at


def test_deleting_website_deletes_check_history(
    tmp_path: Path,
) -> None:
    with database_session(tmp_path / "cascade.sqlite3") as connection:
        apply_pending_migrations(
            connection,
            MIGRATION_DIR,
        )

        website_id = _seed_website(connection)

        insert_website_check(
            connection,
            WebsiteCheck(
                website_id=website_id,
                requested_url="https://example.ca/",
            ),
        )

        connection.execute(
            "DELETE FROM websites WHERE id = ?",
            (website_id,),
        )
        connection.commit()

        count = connection.execute("SELECT COUNT(*) FROM website_checks").fetchone()[0]

        assert count == 0
