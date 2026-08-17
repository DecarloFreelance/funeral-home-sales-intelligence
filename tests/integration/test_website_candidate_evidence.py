from __future__ import annotations

import json
from pathlib import Path

from canada_funeral_intel.normalization.execution import normalize_source_records
from canada_funeral_intel.storage import database_session
from canada_funeral_intel.storage.migrations import apply_pending_migrations
from canada_funeral_intel.verification.discovery import discover_website_candidates
from canada_funeral_intel.verification.website_cli import run_website_list

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "database" / "migrations"


def _seed(path: Path) -> None:
    with database_session(path) as connection:
        assert (
            apply_pending_migrations(connection, MIGRATIONS).status.current_version
            == 27
        )
        connection.execute(
            "INSERT INTO source_datasets (id,name,source_type,jurisdiction) VALUES (1,'Fixture','manual','CA')"
        )
        connection.execute(
            "INSERT INTO entities (id,entity_type,canonical_name) VALUES (1,'branch','Alpha Funeral')"
        )
        for record_id, email, url in (
            (1, "info@alpha.example", "https://alpha.example/team"),
            (2, "admin@alpha.example", None),
            (3, "owner@gmail.com", None),
        ):
            connection.execute(
                "INSERT INTO source_records (id,source_dataset_id,raw_payload,payload_format,source_url,retrieved_at,checksum) VALUES (?,1,'{}','json','fixture://record', '2026-01-01T00:00:00Z',?)",
                (record_id, f"checksum-{record_id}"),
            )
            connection.execute(
                "INSERT INTO entity_source_records (entity_id,source_record_id,membership_role) VALUES (1,?,'location')",
                (record_id,),
            )
            if email:
                connection.execute(
                    "INSERT INTO normalized_values (source_record_id,field_name,original_value,normalized_value,normalizer_name,normalizer_version,normalized_at) VALUES (?, 'email', ?, ?, 'email', '1', '2026-01-01T00:00:00Z')",
                    (record_id, email, email),
                )
            if url:
                connection.execute(
                    "INSERT INTO normalized_values (source_record_id,field_name,original_value,normalized_value,normalizer_name,normalizer_version,normalized_at) VALUES (?, 'url', ?, ?, 'url', '1', '2026-01-01T00:00:00Z')",
                    (record_id, url, url),
                )
        connection.commit()


def test_explicit_and_email_evidence_share_one_candidate(tmp_path: Path) -> None:
    path = tmp_path / "evidence.sqlite3"
    _seed(path)
    with database_session(path) as connection:
        result = discover_website_candidates(connection)
        assert result.candidates_inserted == 1
        assert result.suppressed_generic_email_signals == 1
        rows = connection.execute(
            "SELECT evidence_class, normalized_value_id FROM website_evidence ORDER BY evidence_class, id"
        ).fetchall()
        assert {row[0] for row in rows} == {"email_domain", "explicit_source_url"}
        assert len(rows) == 5
        payload = run_website_list(connection, entity_id=1)
    assert payload[0]["strongest_evidence"] == "explicit_source_url"
    assert payload[0]["supporting_evidence_count"] == 4
    assert payload[0]["source_record_ids"] == [1, 2]
    assert payload[0]["shared_domain"] is False
    json.dumps(payload, sort_keys=True)


def test_evidence_summary_is_deterministic_and_rerun_is_idempotent(
    tmp_path: Path,
) -> None:
    path = tmp_path / "repeat.sqlite3"
    _seed(path)
    with database_session(path) as connection:
        first = discover_website_candidates(connection)
        second = discover_website_candidates(connection)
        assert first.candidates_inserted == 1
        assert second.candidates_inserted == 0
        assert second.evidence_inserted == 0
        first_payload = run_website_list(connection, entity_id=1)
        second_payload = run_website_list(connection, entity_id=1)
    assert first_payload == second_payload


def test_migration_reapply_is_noop(tmp_path: Path) -> None:
    path = tmp_path / "migration.sqlite3"
    with database_session(path) as connection:
        first = apply_pending_migrations(connection, MIGRATIONS)
        second = apply_pending_migrations(connection, MIGRATIONS)
        assert first.status.current_version == 27
        assert [item.version for item in second.applied] == []
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(website_evidence)")
        }
        assert {
            "normalized_value_id",
            "evidence_class",
            "derivation_version",
            "raw_value",
        } <= columns


def test_explicit_source_field_normalizes_and_out_ranks_generic_signals(
    tmp_path: Path,
) -> None:
    path = tmp_path / "explicit.sqlite3"
    with database_session(path) as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        connection.execute(
            "INSERT INTO source_datasets (id,name,source_type,jurisdiction) VALUES (1,'Fixture','manual','CA')"
        )
        connection.execute(
            "INSERT INTO entities (id,entity_type,canonical_name) VALUES (1,'organization','Alpha')"
        )
        connection.execute(
            "INSERT INTO source_records (id,source_dataset_id,raw_payload,payload_format,source_url,retrieved_at,checksum) VALUES (1,1,?,'json','fixture://source','2026-01-01T00:00:00Z','checksum')",
            (
                json.dumps(
                    {
                        "official_website": "HTTPS://Alpha.Example/",
                        "email": "info@alpha.example",
                    }
                ),
            ),
        )
        connection.execute(
            "INSERT INTO entity_source_records (entity_id,source_record_id,membership_role) VALUES (1,1,'organization')"
        )
        connection.commit()
        normalize_source_records(connection)
        result = discover_website_candidates(connection)
        payload = run_website_list(connection, entity_id=1)
        fields = [
            row[0]
            for row in connection.execute(
                "SELECT field_name FROM normalized_values ORDER BY id"
            )
        ]
        classes = [
            row[0]
            for row in connection.execute(
                "SELECT evidence_class FROM website_evidence ORDER BY id"
            )
        ]
    assert result.candidates_inserted == 1
    assert "explicit_website_url" in fields
    assert payload[0]["strongest_evidence"] == "explicit_source_website"
    assert "explicit_source_website" in classes
