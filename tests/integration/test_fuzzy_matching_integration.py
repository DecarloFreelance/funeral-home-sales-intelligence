from __future__ import annotations

import sqlite3
from pathlib import Path

from canada_funeral_intel.deduplication.fuzzy import generate_fuzzy_matches
from canada_funeral_intel.storage import database_session
from canada_funeral_intel.storage.migrations import apply_pending_migrations

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "database" / "migrations"


def _prepare_database(connection: sqlite3.Connection) -> None:
    result = apply_pending_migrations(connection, MIGRATIONS)
    assert result.status.current_version == 21

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


def test_fuzzy_match_run_persists_weighted_candidate_and_evidence(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "fuzzy.sqlite3"

    with database_session(database_path) as connection:
        _prepare_database(connection)
        left_id = _insert_source_record(connection, "left")
        right_id = _insert_source_record(connection, "right")

        left_values = {
            "business_name": "smith funeral home",
            "city": "Calgary",
            "province": "AB",
        }
        right_values = {
            "business_name": "smiths funeral home",
            "city": "Calgary",
            "province": "AB",
        }
        for field_name, value in left_values.items():
            _insert_normalized(connection, left_id, field_name, value)
        for field_name, value in right_values.items():
            _insert_normalized(connection, right_id, field_name, value)

        connection.commit()
        result = generate_fuzzy_matches(connection)

        assert result.records_seen == 2
        assert result.blocked_pairs == 1
        assert result.pairs_scored == 1
        assert result.candidates_inserted == 1
        assert result.candidates_unchanged == 0
        assert result.evidence_inserted == 3

        candidate = connection.execute(
            """
            SELECT candidate_method, score, decision
            FROM match_candidates
            """
        ).fetchone()
        assert candidate["candidate_method"] == "fuzzy_weighted_v1"
        assert candidate["score"] > 0.95
        assert candidate["decision"] == "review"

        evidence = connection.execute(
            """
            SELECT signal_name, contribution, evidence_kind
            FROM match_evidence
            ORDER BY signal_name
            """
        ).fetchall()
        assert [row["signal_name"] for row in evidence] == [
            "business_name",
            "city",
            "province",
        ]
        assert {row["evidence_kind"] for row in evidence} == {"fuzzy", "context"}


def test_fuzzy_match_run_is_idempotent(tmp_path: Path) -> None:
    database_path = tmp_path / "fuzzy.sqlite3"

    with database_session(database_path) as connection:
        _prepare_database(connection)
        left_id = _insert_source_record(connection, "left")
        right_id = _insert_source_record(connection, "right")

        for source_record_id, name in (
            (left_id, "smith funeral home"),
            (right_id, "smiths funeral home"),
        ):
            _insert_normalized(connection, source_record_id, "business_name", name)
            _insert_normalized(connection, source_record_id, "city", "Calgary")
            _insert_normalized(connection, source_record_id, "province", "AB")

        connection.commit()
        first = generate_fuzzy_matches(connection)
        second = generate_fuzzy_matches(connection)

        assert first.candidates_inserted == 1
        assert second.candidates_inserted == 0
        assert second.candidates_unchanged == 1
        assert second.evidence_inserted == 0
        assert (
            connection.execute("SELECT COUNT(*) FROM match_candidates").fetchone()[0]
            == 1
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM match_evidence").fetchone()[0] == 3
        )


def test_fuzzy_generation_does_not_pair_every_record(tmp_path: Path) -> None:
    database_path = tmp_path / "fuzzy.sqlite3"

    with database_session(database_path) as connection:
        _prepare_database(connection)
        left_id = _insert_source_record(connection, "left")
        right_id = _insert_source_record(connection, "right")

        _insert_normalized(
            connection,
            left_id,
            "business_name",
            "smith funeral home",
        )
        _insert_normalized(connection, left_id, "city", "Calgary")
        _insert_normalized(connection, left_id, "province", "AB")

        _insert_normalized(
            connection,
            right_id,
            "business_name",
            "smiths funeral home",
        )
        _insert_normalized(connection, right_id, "city", "Edmonton")
        _insert_normalized(connection, right_id, "province", "AB")

        connection.commit()
        result = generate_fuzzy_matches(connection)

        assert result.records_seen == 2
        assert result.blocked_pairs == 0
        assert result.pairs_scored == 0
        assert result.candidates_inserted == 0


def test_fuzzy_and_deterministic_candidates_can_coexist(tmp_path: Path) -> None:
    from canada_funeral_intel.deduplication.deterministic import (
        generate_deterministic_matches,
    )

    database_path = tmp_path / "fuzzy.sqlite3"

    with database_session(database_path) as connection:
        _prepare_database(connection)
        left_id = _insert_source_record(connection, "left")
        right_id = _insert_source_record(connection, "right")

        for source_record_id, name in (
            (left_id, "smith funeral home"),
            (right_id, "smiths funeral home"),
        ):
            _insert_normalized(connection, source_record_id, "business_name", name)
            _insert_normalized(connection, source_record_id, "city", "Calgary")
            _insert_normalized(connection, source_record_id, "province", "AB")
            _insert_normalized(
                connection,
                source_record_id,
                "phone",
                "+14035550100",
            )

        connection.commit()
        generate_deterministic_matches(connection)
        generate_fuzzy_matches(connection)

        methods = {
            row["candidate_method"]
            for row in connection.execute(
                "SELECT candidate_method FROM match_candidates"
            )
        }
        assert methods == {"deterministic_v1", "fuzzy_weighted_v1"}
