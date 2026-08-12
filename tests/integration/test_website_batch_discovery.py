from __future__ import annotations

from pathlib import Path

import pytest

from canada_funeral_intel.storage import database_session
from canada_funeral_intel.storage.migrations import apply_pending_migrations
from canada_funeral_intel.verification.batch import (
    BatchLimits,
    WebsiteBatchError,
    batch_verify,
    populate_candidates,
)
from canada_funeral_intel.verification.checks import (
    DNSStatus,
    TLSStatus,
    WebsiteCheck,
    WebsiteCheckOutcome,
)

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "database" / "migrations"


def _fixture(path: Path) -> None:
    with database_session(path) as connection:
        assert apply_pending_migrations(connection, MIGRATIONS).status.current_version == 21
        connection.execute("INSERT INTO source_datasets (id,name,source_type,jurisdiction,is_active) VALUES (1,'Fixture','manual','AB',1)")
        for entity_id, name in ((1, "Alpha Funeral"), (2, "Beta Funeral")):
            connection.execute("INSERT INTO entities (id,entity_type,canonical_name,status) VALUES (?, 'branch', ?, 'active')", (entity_id, name))
            connection.execute("INSERT INTO source_records (id,source_dataset_id,raw_payload,payload_format,source_url,retrieved_at,checksum) VALUES (?,1,'{}','json','fixture://source','2026-01-01T00:00:00Z',?)", (entity_id, f"checksum-{entity_id}"))
            connection.execute("INSERT INTO entity_source_records (entity_id,source_record_id,membership_role) VALUES (?,?,'branch')", (entity_id, entity_id))
        for record_id, field, value in ((1, "url", "https://shared.example/alpha"), (2, "email", "info@shared.example")):
            connection.execute("INSERT INTO normalized_values (source_record_id,field_name,original_value,normalized_value,normalizer_name,normalizer_version,normalized_at) VALUES (?,?,?,?,?,'1','2026-01-01T00:00:00Z')", (record_id, field, value, value, field))
        connection.commit()


def test_offline_population_is_idempotent_and_shared_domain_safe(tmp_path: Path) -> None:
    path = tmp_path / "website.sqlite3"
    _fixture(path)
    with database_session(path) as connection:
        first = populate_candidates(connection, limits=BatchLimits(entity_limit=10, candidate_limit=2))
        second = populate_candidates(connection, limits=BatchLimits(entity_limit=10, candidate_limit=2))
        rows = connection.execute("SELECT entity_id, domain, website_kind, status, is_primary FROM websites ORDER BY entity_id").fetchall()
    assert first["network_used"] is False
    assert first["candidates_inserted"] == 2
    assert second["candidates_inserted"] == 0
    assert second["candidates_unchanged"] == 2
    assert [(row["entity_id"], row["domain"]) for row in rows] == [(1, "shared.example"), (2, "shared.example")]
    assert rows[0]["website_kind"] == "branch"
    assert rows[0]["status"] == "candidate"
    assert rows[1]["website_kind"] == "shared"
    assert rows[1]["status"] == "review"
    assert all(row["is_primary"] == 0 for row in rows)


def test_population_dry_run_does_not_write_or_call_network(tmp_path: Path) -> None:
    path = tmp_path / "dry.sqlite3"
    _fixture(path)
    with database_session(path) as connection:
        before = connection.total_changes
        result = populate_candidates(connection, dry_run=True)
        assert result["network_used"] is False
        assert result["dry_run"] is True
        assert connection.total_changes == before
        assert connection.execute("SELECT COUNT(*) FROM websites").fetchone()[0] == 0


def test_batch_verify_requires_authorization(tmp_path: Path) -> None:
    path = tmp_path / "auth.sqlite3"
    _fixture(path)
    with database_session(path) as connection:
        populate_candidates(connection)
        with pytest.raises(WebsiteBatchError, match="allow-network"):
            batch_verify(connection, allow_network=False)
        assert connection.execute("SELECT COUNT(*) FROM website_checks").fetchone()[0] == 0


def test_network_batch_dry_run_is_non_network_and_non_persistent(tmp_path: Path) -> None:
    path = tmp_path / "network-dry.sqlite3"
    _fixture(path)
    with database_session(path) as connection:
        populate_candidates(connection)
        before = connection.total_changes
        result = batch_verify(connection, allow_network=False, dry_run=True)
        assert result["network_used"] is False
        assert result["projected_candidates"] == 2
        assert connection.total_changes == before
        assert connection.execute("SELECT COUNT(*) FROM website_discovery_runs WHERE mode='network_verify'").fetchone()[0] == 0


def test_batch_verify_is_bounded_and_resumable_with_fixture_verifier(tmp_path: Path) -> None:
    path = tmp_path / "verify.sqlite3"
    _fixture(path)
    calls: list[int] = []

    def verifier(**kwargs: object) -> WebsiteCheck:
        website_id = int(kwargs["website_id"])
        calls.append(website_id)
        return WebsiteCheck(website_id=website_id, requested_url=str(kwargs["url"]), dns_status=DNSStatus.OK, tls_status=TLSStatus.OK, https_status_code=200, outcome=WebsiteCheckOutcome.REACHABLE)

    with database_session(path) as connection:
        populate_candidates(connection)
        result = batch_verify(connection, allow_network=True, limits=BatchLimits(entity_limit=1, candidate_limit=1), verifier=verifier)
        with pytest.raises(WebsiteBatchError, match="completed"):
            batch_verify(connection, allow_network=True, resume_run_id=int(result["run_id"]), verifier=verifier)
        assert result["network_used"] is True
        assert result["succeeded"] == 1
        assert len(calls) == 1
        assert connection.execute("SELECT COUNT(*) FROM website_checks").fetchone()[0] == 1


def test_transient_verification_failure_retries_once(tmp_path: Path) -> None:
    path = tmp_path / "retry.sqlite3"
    _fixture(path)
    calls = {"count": 0}

    def verifier(**kwargs: object) -> WebsiteCheck:
        calls["count"] += 1
        if calls["count"] == 1:
            return WebsiteCheck(website_id=int(kwargs["website_id"]), requested_url=str(kwargs["url"]), error_message="HTTP request failed: timeout")
        return WebsiteCheck(website_id=int(kwargs["website_id"]), requested_url=str(kwargs["url"]), dns_status=DNSStatus.OK, tls_status=TLSStatus.OK, https_status_code=200, outcome=WebsiteCheckOutcome.REACHABLE)

    with database_session(path) as connection:
        populate_candidates(connection)
        result = batch_verify(connection, allow_network=True, limits=BatchLimits(entity_limit=1, candidate_limit=1, max_retries=1), verifier=verifier)
        item = connection.execute("SELECT status, attempts FROM website_discovery_run_items").fetchone()
    assert result["status"] == "completed"
    assert calls["count"] == 2
    assert item["status"] == "completed"
    assert item["attempts"] == 2
