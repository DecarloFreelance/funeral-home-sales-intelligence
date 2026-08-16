from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from canada_funeral_intel.business_intelligence.cli import (
    BusinessFactCommandError,
    run_business_facts_extract,
)
from canada_funeral_intel.extraction.page_people import extract_website_people
from canada_funeral_intel.storage.database import connect_database, database_session
from canada_funeral_intel.storage.migrations import apply_pending_migrations
from canada_funeral_intel.verification.batch import BatchLimits, batch_verify
from canada_funeral_intel.verification.checks import (
    DNSStatus,
    TLSStatus,
    WebsiteCheck,
    WebsiteCheckOutcome,
)
from canada_funeral_intel.verification.page_discovery import (
    DiscoveredPage,
    discover_website_pages,
    upsert_website_page,
)
from canada_funeral_intel.verification.page_fetch import (
    PageFetchStateError,
    record_page_fetch,
)
from canada_funeral_intel.verification.probe import HTTPProbeResult
from canada_funeral_intel.verification.storage import (
    make_website_candidate,
    upsert_website_candidate,
)
from canada_funeral_intel.verification.website_cli import run_website_verify

MIGRATIONS = Path(__file__).resolve().parents[2] / "database" / "migrations"


def _result(
    url: str,
    *,
    status: int | None = 200,
    body: bytes = b"<html><body></body></html>",
    content_type: str | None = "text/html",
    error: str | None = None,
) -> HTTPProbeResult:
    return HTTPProbeResult(
        requested_url=url,
        final_url=url if status is not None else None,
        status_code=status,
        redirect_count=0,
        response_time_ms=1,
        content_type=content_type,
        canonical_url=None,
        error_message=error,
        body=body,
    )


def _seed(connection: sqlite3.Connection) -> tuple[int, int, int]:
    entity = connection.execute(
        "INSERT INTO entities (entity_type, canonical_name) VALUES ('organization', 'Fetch Fixture')"
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
        ),
    ).website_id
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
        ),
    )
    connection.commit()
    return entity_id, website_id, page_id


def _fetch_state(connection, page_id: int) -> sqlite3.Row:
    row = connection.execute(
        "SELECT last_fetched_at, last_success_at, last_failure_at, last_status_code, last_content_type, last_error, last_content_hash FROM website_pages WHERE id = ?",
        (page_id,),
    ).fetchone()
    assert row is not None
    return row


def test_fetch_state_migration_is_nullable_for_existing_pages(tmp_path: Path) -> None:
    with database_session(tmp_path / "nullable.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        _, _, page_id = _seed(connection)
        state = _fetch_state(connection, page_id)

    assert tuple(state) == (None, None, None, None, None, None, None)


def test_fetch_state_preserves_history_across_failures_and_successes(
    tmp_path: Path,
) -> None:
    with database_session(tmp_path / "state.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        _, _, page_id = _seed(connection)

        record_page_fetch(
            connection,
            website_page_id=page_id,
            result=_result("https://example.ca/team", body=b"first"),
        )
        first = _fetch_state(connection, page_id)
        record_page_fetch(
            connection,
            website_page_id=page_id,
            result=_result(
                "https://example.ca/team",
                status=None,
                error="fixture timeout",
            ),
        )
        failed = _fetch_state(connection, page_id)
        record_page_fetch(
            connection,
            website_page_id=page_id,
            result=_result("https://example.ca/team", body=b"second"),
        )
        recovered = _fetch_state(connection, page_id)

    assert first["last_success_at"] is not None
    assert first["last_content_hash"] is not None
    assert failed["last_failure_at"] is not None
    assert failed["last_error"] == "fixture timeout"
    assert failed["last_success_at"] == first["last_success_at"]
    assert failed["last_content_hash"] == first["last_content_hash"]
    assert recovered["last_success_at"] != first["last_success_at"]
    assert recovered["last_failure_at"] == failed["last_failure_at"]
    assert recovered["last_error"] is None
    assert recovered["last_content_hash"] != first["last_content_hash"]


def test_successful_fetch_state_is_durable_after_reopen(tmp_path: Path) -> None:
    database_path = tmp_path / "durable.sqlite3"
    with database_session(database_path) as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        _, _, page_id = _seed(connection)
        record_page_fetch(
            connection,
            website_page_id=page_id,
            result=_result("https://example.ca/team", body=b"durable"),
        )

    with database_session(database_path) as connection:
        state = _fetch_state(connection, page_id)

    assert state["last_success_at"] is not None
    assert state["last_content_hash"] is not None


def test_empty_successful_body_has_sha256_empty_hash(tmp_path: Path) -> None:
    with database_session(tmp_path / "empty-body.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        _, _, page_id = _seed(connection)
        record_page_fetch(
            connection,
            website_page_id=page_id,
            result=_result("https://example.ca/team", body=b""),
        )
        state = _fetch_state(connection, page_id)

    assert state["last_content_hash"] == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


def test_http_rejection_is_retrieved_and_hashes_body(tmp_path: Path) -> None:
    with database_session(tmp_path / "http-rejection.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        _, _, page_id = _seed(connection)
        record_page_fetch(
            connection,
            website_page_id=page_id,
            result=_result(
                "https://example.ca/team",
                status=503,
                body=b"<html><body>temporarily unavailable</body></html>",
            ),
        )
        state = _fetch_state(connection, page_id)

    assert state["last_success_at"] is not None
    assert state["last_failure_at"] is None
    assert state["last_status_code"] == 503
    assert state["last_content_hash"] is not None


def test_fetch_state_rejects_open_caller_transaction_without_touching_it(
    tmp_path: Path,
) -> None:
    with database_session(tmp_path / "caller-transaction.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        _, _, page_id = _seed(connection)
        connection.execute(
            "INSERT INTO entities (entity_type, canonical_name) VALUES ('organization', 'Uncommitted Fixture')"
        )

        with pytest.raises(PageFetchStateError, match="open transaction"):
            record_page_fetch(
                connection,
                website_page_id=page_id,
                result=_result("https://example.ca/team"),
            )

        assert connection.in_transaction is True
        assert (
            connection.execute(
                "SELECT 1 FROM entities WHERE canonical_name = 'Uncommitted Fixture'"
            ).fetchone()
            is not None
        )
        state = _fetch_state(connection, page_id)
        assert state["last_success_at"] is None
        connection.rollback()


def test_in_memory_fetch_state_is_transaction_safe() -> None:
    connection = connect_database(":memory:")
    try:
        apply_pending_migrations(connection, MIGRATIONS)
        _, _, page_id = _seed(connection)
        record_page_fetch(
            connection,
            website_page_id=page_id,
            result=_result("https://example.ca/team", body=b"memory"),
        )
        assert _fetch_state(connection, page_id)["last_success_at"] is not None

        connection.execute(
            "INSERT INTO entities (entity_type, canonical_name) VALUES ('organization', 'Memory Fixture')"
        )
        with pytest.raises(PageFetchStateError, match="open transaction"):
            record_page_fetch(
                connection,
                website_page_id=page_id,
                result=_result("https://example.ca/team", body=b"blocked"),
            )
        connection.rollback()
    finally:
        connection.close()


def test_fetch_state_missing_page_does_not_commit_caller_work(
    tmp_path: Path,
) -> None:
    with database_session(tmp_path / "missing-page.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        connection.execute(
            "INSERT INTO entities (entity_type, canonical_name) VALUES ('organization', 'Uncommitted Fixture')"
        )
        with pytest.raises(PageFetchStateError, match="open transaction"):
            record_page_fetch(
                connection,
                website_page_id=999999,
                result=_result("https://example.ca/missing"),
            )
        assert (
            connection.execute(
                "SELECT 1 FROM entities WHERE canonical_name = 'Uncommitted Fixture'"
            ).fetchone()
            is not None
        )
        connection.rollback()


def test_fetch_state_missing_page_is_rejected(tmp_path: Path) -> None:
    with database_session(tmp_path / "missing-page-rejected.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        with pytest.raises(PageFetchStateError, match="page not found"):
            record_page_fetch(
                connection,
                website_page_id=999999,
                result=_result("https://example.ca/missing"),
            )


def test_concurrent_writers_update_different_pages(tmp_path: Path) -> None:
    database_path = tmp_path / "concurrent-pages.sqlite3"
    with database_session(database_path) as connection:
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
                priority_score=80,
                depth=1,
            ),
        )
        connection.commit()

    def write(page_id: int, body: bytes) -> None:
        with database_session(database_path) as connection:
            record_page_fetch(
                connection,
                website_page_id=page_id,
                result=_result("https://example.ca/page", body=body),
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(
            executor.map(
                lambda values: write(*values),
                ((first_page_id, b"first"), (second_page_id, b"second")),
            )
        )

    with database_session(database_path) as connection:
        states = connection.execute(
            "SELECT last_success_at, last_content_hash FROM website_pages WHERE id IN (?, ?) ORDER BY id",
            (first_page_id, second_page_id),
        ).fetchall()

    assert len(states) == 2
    assert all(row["last_success_at"] is not None for row in states)
    assert all(row["last_content_hash"] is not None for row in states)


def test_page_discovery_records_success_and_failure_fetch_state(
    monkeypatch,
    tmp_path: Path,
) -> None:
    response = _result(
        "https://example.ca/",
        body=b"<html><body>Fetch Fixture</body></html>",
    )

    monkeypatch.setattr(
        "canada_funeral_intel.verification.page_discovery.probe_http",
        lambda *args, **kwargs: response,
    )
    with database_session(tmp_path / "discovery-state.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        website_id = _seed(connection)[1]
        discover_website_pages(
            connection,
            website_id=website_id,
            user_agent="Fixture/1.0",
            timeout_seconds=5,
            max_redirects=2,
            max_pages=1,
            max_depth=0,
        )
        row = connection.execute(
            "SELECT normalized_url, last_success_at, last_content_hash FROM website_pages WHERE website_id = ? AND path = '/'",
            (website_id,),
        ).fetchone()

    assert row["normalized_url"] == "https://example.ca/"
    assert row["last_success_at"] is not None
    assert row["last_content_hash"] is not None

    failed_response = _result(
        "https://example.ca/",
        status=None,
        error="fixture DNS failure",
    )
    monkeypatch.setattr(
        "canada_funeral_intel.verification.page_discovery.probe_http",
        lambda *args, **kwargs: failed_response,
    )
    with database_session(tmp_path / "discovery-failure.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        website_id = _seed(connection)[1]
        discover_website_pages(
            connection,
            website_id=website_id,
            user_agent="Fixture/1.0",
            timeout_seconds=5,
            max_redirects=2,
            max_pages=1,
            max_depth=0,
        )
        row = connection.execute(
            "SELECT last_failure_at, last_error FROM website_pages WHERE website_id = ? AND path = '/'",
            (website_id,),
        ).fetchone()

    assert row["last_failure_at"] is not None
    assert row["last_error"] == "fixture DNS failure"


def test_people_success_zero_observations_records_page_hash(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "canada_funeral_intel.extraction.page_people.probe_http",
        lambda *args, **kwargs: _result(
            "https://example.ca/team",
            body=b"<html><body>No staff listed.</body></html>",
        ),
    )
    with database_session(tmp_path / "people-state.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        _, website_id, page_id = _seed(connection)
        result = extract_website_people(
            connection,
            website_id=website_id,
            user_agent="Fixture/1.0",
            timeout_seconds=5,
            max_redirects=2,
        )
        state = _fetch_state(connection, page_id)

    assert result.candidates_found == 0
    assert state["last_success_at"] is not None
    assert state["last_content_hash"] is not None


def test_people_extraction_failure_does_not_erase_successful_fetch_state(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "canada_funeral_intel.extraction.page_people.probe_http",
        lambda *args, **kwargs: _result("https://example.ca/team"),
    )
    monkeypatch.setattr(
        "canada_funeral_intel.extraction.page_people.analyze_person_page",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("fixture extraction failure")
        ),
    )
    with database_session(tmp_path / "people-error.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        _, website_id, page_id = _seed(connection)
        with pytest.raises(RuntimeError, match="fixture extraction failure"):
            extract_website_people(
                connection,
                website_id=website_id,
                user_agent="Fixture/1.0",
                timeout_seconds=5,
                max_redirects=2,
            )
        state = _fetch_state(connection, page_id)

    assert state["last_success_at"] is not None
    assert state["last_failure_at"] is None


def test_people_current_probe_failure_records_failure_state(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "canada_funeral_intel.extraction.page_people.probe_http",
        lambda *args, **kwargs: _result(
            "https://example.ca/team",
            status=None,
            error="fixture connection failure",
        ),
    )
    with database_session(tmp_path / "people-failure.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        _, website_id, page_id = _seed(connection)
        extract_website_people(
            connection,
            website_id=website_id,
            user_agent="Fixture/1.0",
            timeout_seconds=5,
            max_redirects=2,
        )
        state = _fetch_state(connection, page_id)

    assert state["last_failure_at"] is not None
    assert state["last_error"] == "fixture connection failure"


def test_business_facts_zero_facts_records_page_hash(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "canada_funeral_intel.business_intelligence.processing.probe_http",
        lambda *args, **kwargs: _result("https://example.ca/team"),
    )
    with database_session(tmp_path / "facts-state.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        _, website_id, page_id = _seed(connection)
        result = run_business_facts_extract(
            connection,
            website_id=website_id,
            page_id=None,
            user_agent="Fixture/1.0",
            timeout_seconds=5,
            max_redirects=2,
        )
        state = _fetch_state(connection, page_id)

    assert result["facts_extracted"] == 0
    assert state["last_success_at"] is not None
    assert state["last_content_hash"] is not None


def test_business_fact_storage_failure_does_not_erase_fetch_success(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "canada_funeral_intel.business_intelligence.processing.probe_http",
        lambda *args, **kwargs: _result(
            "https://example.ca/team",
            body=b"<main>Family-owned since 1984.</main>",
        ),
    )
    monkeypatch.setattr(
        "canada_funeral_intel.business_intelligence.processing.store_business_facts",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            sqlite3.IntegrityError("fixture storage failure")
        ),
    )
    with database_session(tmp_path / "facts-error.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        _, website_id, page_id = _seed(connection)
        with pytest.raises(BusinessFactCommandError, match="fixture storage failure"):
            run_business_facts_extract(
                connection,
                website_id=website_id,
                page_id=None,
                user_agent="Fixture/1.0",
                timeout_seconds=5,
                max_redirects=2,
            )
        state = _fetch_state(connection, page_id)

    assert state["last_success_at"] is not None
    assert state["last_content_hash"] is not None


def test_website_verification_does_not_write_page_fetch_state(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with database_session(tmp_path / "website-boundary.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        _, website_id, page_id = _seed(connection)
        monkeypatch.setattr(
            "canada_funeral_intel.verification.website_cli.probe_website",
            lambda **kwargs: WebsiteCheck(
                website_id=website_id,
                requested_url="https://example.ca/",
                dns_status=DNSStatus.OK,
                tls_status=TLSStatus.OK,
                https_status_code=200,
                outcome=WebsiteCheckOutcome.REACHABLE,
            ),
        )
        run_website_verify(
            connection,
            website_id=website_id,
            user_agent="Fixture/1.0",
            timeout_seconds=5,
            max_redirects=2,
        )
        state = _fetch_state(connection, page_id)

    assert tuple(state) == (None, None, None, None, None, None, None)


def test_batch_verification_does_not_write_page_fetch_state(tmp_path: Path) -> None:
    with database_session(tmp_path / "batch-boundary.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        _, _website_id, page_id = _seed(connection)
        result = batch_verify(
            connection,
            allow_network=True,
            limits=BatchLimits(entity_limit=1, candidate_limit=1),
            verifier=lambda **kwargs: WebsiteCheck(
                website_id=int(kwargs["website_id"]),
                requested_url=str(kwargs["url"]),
                dns_status=DNSStatus.OK,
                tls_status=TLSStatus.OK,
                https_status_code=200,
                outcome=WebsiteCheckOutcome.REACHABLE,
            ),
        )
        state = _fetch_state(connection, page_id)

    assert result["succeeded"] == 1
    assert tuple(state) == (None, None, None, None, None, None, None)
