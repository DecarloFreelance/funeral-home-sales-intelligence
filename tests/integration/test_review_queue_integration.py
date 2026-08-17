from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from canada_funeral_intel.deduplication.review import (
    ReviewQueueError,
    ReviewStatus,
    apply_review_decision,
    list_review_queue,
    populate_review_queue,
)
from canada_funeral_intel.storage import database_session
from canada_funeral_intel.storage.migrations import apply_pending_migrations

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "database" / "migrations"


def _prepare_database(connection: sqlite3.Connection) -> None:
    result = apply_pending_migrations(connection, MIGRATIONS)
    assert result.status.current_version == 27
    connection.execute(
        """
        INSERT INTO source_datasets (id, name, source_type, jurisdiction, is_active)
        VALUES (1, 'Fixture Source', 'manual', 'AB', 1)
        """
    )


def _insert_source_record(connection: sqlite3.Connection, external_id: str) -> int:
    cursor = connection.execute(
        """
        INSERT INTO source_records (
            source_dataset_id, external_record_id, raw_payload, payload_format,
            source_url, retrieved_at, checksum
        )
        VALUES (
            1, ?, '{}', 'json', 'https://example.test/record',
            '2026-08-08T00:00:00+00:00', ?
        )
        """,
        (external_id, f"checksum-{external_id}"),
    )
    assert cursor.lastrowid is not None
    return int(cursor.lastrowid)


def _insert_candidate(
    connection: sqlite3.Connection,
    *,
    suffix: str,
    score: float,
    decision: str = "review",
) -> int:
    left_id = _insert_source_record(connection, f"{suffix}-left")
    right_id = _insert_source_record(connection, f"{suffix}-right")
    cursor = connection.execute(
        """
        INSERT INTO match_candidates (
            left_source_record_id, right_source_record_id,
            candidate_method, score, decision
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (left_id, right_id, f"fixture_{suffix}", score, decision),
    )
    assert cursor.lastrowid is not None
    return int(cursor.lastrowid)


def test_populate_review_queue_is_filtered_and_idempotent(tmp_path: Path) -> None:
    database_path = tmp_path / "review.sqlite3"
    with database_session(database_path) as connection:
        _prepare_database(connection)
        review_id = _insert_candidate(connection, suffix="review", score=0.90)
        _insert_candidate(connection, suffix="match", score=1.0, decision="match")
        connection.commit()

        first = populate_review_queue(connection)
        second = populate_review_queue(connection)

        assert first.review_candidates_seen == 1
        assert first.queue_entries_inserted == 1
        assert first.queue_entries_unchanged == 0
        assert second.queue_entries_inserted == 0
        assert second.queue_entries_unchanged == 1
        row = connection.execute(
            "SELECT match_candidate_id, priority, status FROM entity_review_queue"
        ).fetchone()
        assert row["match_candidate_id"] == review_id
        assert row["priority"] == 100
        assert row["status"] == "pending"


def test_review_queue_lists_highest_score_first(tmp_path: Path) -> None:
    database_path = tmp_path / "review.sqlite3"
    with database_session(database_path) as connection:
        _prepare_database(connection)
        high_id = _insert_candidate(connection, suffix="high", score=0.90)
        low_id = _insert_candidate(connection, suffix="low", score=0.70)
        connection.commit()
        populate_review_queue(connection)
        entries = list_review_queue(connection)
        assert [entry.match_candidate_id for entry in entries] == [high_id, low_id]
        assert entries[0].priority < entries[1].priority


def test_approve_review_updates_candidate_atomically(tmp_path: Path) -> None:
    database_path = tmp_path / "review.sqlite3"
    with database_session(database_path) as connection:
        _prepare_database(connection)
        candidate_id = _insert_candidate(connection, suffix="approve", score=0.90)
        connection.commit()
        populate_review_queue(connection)
        queue_id = int(
            connection.execute("SELECT id FROM entity_review_queue").fetchone()["id"]
        )
        result = apply_review_decision(
            connection,
            queue_id=queue_id,
            status=ReviewStatus.APPROVED,
            reviewer_note="same location confirmed",
        )
        assert result.match_candidate_id == candidate_id
        assert result.review_status is ReviewStatus.APPROVED
        assert result.candidate_decision.value == "match"
        assert result.reviewer_note == "same location confirmed"
        assert result.reviewed_at
        candidate = connection.execute(
            "SELECT decision FROM match_candidates WHERE id = ?", (candidate_id,)
        ).fetchone()
        queue = connection.execute(
            "SELECT status, reviewer_note, reviewed_at FROM entity_review_queue WHERE id = ?",
            (queue_id,),
        ).fetchone()
        assert candidate["decision"] == "match"
        assert queue["status"] == "approved"
        assert queue["reviewer_note"] == "same location confirmed"
        assert queue["reviewed_at"] is not None


def test_reject_review_sets_no_match(tmp_path: Path) -> None:
    database_path = tmp_path / "review.sqlite3"
    with database_session(database_path) as connection:
        _prepare_database(connection)
        candidate_id = _insert_candidate(connection, suffix="reject", score=0.80)
        connection.commit()
        populate_review_queue(connection)
        queue_id = int(
            connection.execute("SELECT id FROM entity_review_queue").fetchone()["id"]
        )
        result = apply_review_decision(
            connection, queue_id=queue_id, status=ReviewStatus.REJECTED
        )
        assert result.candidate_decision.value == "no_match"
        assert (
            connection.execute(
                "SELECT decision FROM match_candidates WHERE id = ?", (candidate_id,)
            ).fetchone()["decision"]
            == "no_match"
        )


def test_deferred_review_can_be_approved_later(tmp_path: Path) -> None:
    database_path = tmp_path / "review.sqlite3"
    with database_session(database_path) as connection:
        _prepare_database(connection)
        _insert_candidate(connection, suffix="defer", score=0.82)
        connection.commit()
        populate_review_queue(connection)
        queue_id = int(
            connection.execute("SELECT id FROM entity_review_queue").fetchone()["id"]
        )
        deferred = apply_review_decision(
            connection,
            queue_id=queue_id,
            status=ReviewStatus.DEFERRED,
            reviewer_note="need another source",
        )
        approved = apply_review_decision(
            connection,
            queue_id=queue_id,
            status=ReviewStatus.APPROVED,
            reviewer_note="confirmed",
        )
        assert deferred.candidate_decision.value == "review"
        assert approved.candidate_decision.value == "match"
        assert approved.review_status is ReviewStatus.APPROVED


def test_finalized_review_cannot_be_changed(tmp_path: Path) -> None:
    database_path = tmp_path / "review.sqlite3"
    with database_session(database_path) as connection:
        _prepare_database(connection)
        _insert_candidate(connection, suffix="final", score=0.84)
        connection.commit()
        populate_review_queue(connection)
        queue_id = int(
            connection.execute("SELECT id FROM entity_review_queue").fetchone()["id"]
        )
        apply_review_decision(
            connection, queue_id=queue_id, status=ReviewStatus.REJECTED
        )
        with pytest.raises(ReviewQueueError, match="already finalized"):
            apply_review_decision(
                connection, queue_id=queue_id, status=ReviewStatus.APPROVED
            )


def test_missing_review_queue_entry_is_rejected(tmp_path: Path) -> None:
    database_path = tmp_path / "review.sqlite3"
    with database_session(database_path) as connection:
        _prepare_database(connection)
        connection.commit()
        with pytest.raises(ReviewQueueError, match="not found"):
            apply_review_decision(
                connection, queue_id=999, status=ReviewStatus.APPROVED
            )
