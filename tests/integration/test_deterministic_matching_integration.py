from __future__ import annotations

import sqlite3
from pathlib import Path

from canada_funeral_intel.deduplication.deterministic import (
    generate_deterministic_matches,
)
from canada_funeral_intel.storage import database_session
from canada_funeral_intel.storage.migrations import apply_pending_migrations

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "database" / "migrations"


def _prepare_database(connection: sqlite3.Connection) -> None:
    result = apply_pending_migrations(connection, MIGRATIONS)
    assert result.status.current_version == 19

    connection.execute(
        """
        INSERT INTO source_datasets (
            id,
            name,
            source_type,
            jurisdiction,
            is_active
        )
        VALUES (
            1,
            'Fixture Source',
            'manual',
            'AB',
            1
        )
        """
    )


def _insert_source_record(
    connection: sqlite3.Connection,
    external_id: str,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO source_records (
            source_dataset_id,
            external_record_id,
            raw_payload,
            payload_format,
            source_url,
            retrieved_at,
            checksum
        )
        VALUES (
            1,
            ?,
            '{}',
            'json',
            'https://example.test/record',
            '2026-08-08T00:00:00+00:00',
            ?
        )
        """,
        (external_id, f"checksum-{external_id}"),
    )
    assert cursor.lastrowid is not None
    return int(cursor.lastrowid)


def _insert_normalized(
    connection: sqlite3.Connection,
    source_record_id: int,
    field_name: str,
    value: str,
) -> None:
    connection.execute(
        """
        INSERT INTO normalized_values (
            source_record_id,
            field_name,
            original_value,
            normalized_value,
            normalizer_name,
            normalizer_version,
            normalized_at,
            warnings
        )
        VALUES (?, ?, ?, ?, ?, '1', '2026-08-08T00:00:00+00:00', '[]')
        """,
        (
            source_record_id,
            field_name,
            value,
            value,
            field_name,
        ),
    )


def test_deterministic_match_run_persists_candidate_and_evidence(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "deterministic.sqlite3"

    with database_session(database_path) as connection:
        _prepare_database(connection)
        left_id = _insert_source_record(connection, "left")
        right_id = _insert_source_record(connection, "right")

        for source_record_id in (left_id, right_id):
            _insert_normalized(
                connection,
                source_record_id,
                "address",
                "123 main street southwest",
            )
            _insert_normalized(
                connection,
                source_record_id,
                "postal_code",
                "T2P 1J9",
            )

        connection.commit()
        result = generate_deterministic_matches(connection)

        assert result.records_seen == 2
        assert result.pairs_found == 1
        assert result.candidates_inserted == 1
        assert result.candidates_unchanged == 0
        assert result.evidence_inserted == 2

        candidate = connection.execute(
            """
            SELECT candidate_method, score, decision
            FROM match_candidates
            """
        ).fetchone()
        assert candidate["candidate_method"] == "deterministic_v1"
        assert candidate["score"] == 0.99
        assert candidate["decision"] == "match"

        evidence = connection.execute(
            """
            SELECT signal_name, evidence_kind
            FROM match_evidence
            ORDER BY signal_name
            """
        ).fetchall()
        assert [(row["signal_name"], row["evidence_kind"]) for row in evidence] == [
            ("address", "deterministic"),
            ("postal_code", "deterministic"),
        ]


def test_deterministic_match_run_is_idempotent(tmp_path: Path) -> None:
    database_path = tmp_path / "deterministic.sqlite3"

    with database_session(database_path) as connection:
        _prepare_database(connection)
        left_id = _insert_source_record(connection, "left")
        right_id = _insert_source_record(connection, "right")

        for source_record_id in (left_id, right_id):
            _insert_normalized(
                connection,
                source_record_id,
                "phone",
                "+14035550100",
            )

        connection.commit()
        first = generate_deterministic_matches(connection)
        second = generate_deterministic_matches(connection)

        assert first.candidates_inserted == 1
        assert second.candidates_inserted == 0
        assert second.candidates_unchanged == 1
        assert second.evidence_inserted == 0
        assert (
            connection.execute("SELECT COUNT(*) FROM match_candidates").fetchone()[0]
            == 1
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM match_evidence").fetchone()[0] == 1
        )


def test_shared_phone_without_location_is_review_candidate(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "deterministic.sqlite3"

    with database_session(database_path) as connection:
        _prepare_database(connection)
        left_id = _insert_source_record(connection, "left")
        right_id = _insert_source_record(connection, "right")

        for source_record_id in (left_id, right_id):
            _insert_normalized(
                connection,
                source_record_id,
                "phone",
                "+14035550100",
            )

        connection.commit()
        generate_deterministic_matches(connection)

        candidate = connection.execute(
            "SELECT score, decision FROM match_candidates"
        ).fetchone()
        assert candidate["score"] == 0.90
        assert candidate["decision"] == "review"


def test_records_without_shared_deterministic_signals_are_ignored(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "deterministic.sqlite3"

    with database_session(database_path) as connection:
        _prepare_database(connection)
        left_id = _insert_source_record(connection, "left")
        right_id = _insert_source_record(connection, "right")

        _insert_normalized(
            connection,
            left_id,
            "postal_code",
            "T2P 1J9",
        )
        _insert_normalized(
            connection,
            right_id,
            "postal_code",
            "V6B 1A1",
        )

        connection.commit()
        result = generate_deterministic_matches(connection)

        assert result.records_seen == 2
        assert result.pairs_found == 0
        assert result.candidates_inserted == 0
        assert result.evidence_inserted == 0
