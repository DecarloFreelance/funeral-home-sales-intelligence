from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import StrEnum

from canada_funeral_intel.deduplication.models import MatchDecision
from canada_funeral_intel.storage.database import transaction


class ReviewQueueError(RuntimeError):
    """Raised when manual review queue operations cannot complete safely."""


class ReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DEFERRED = "deferred"


@dataclass(frozen=True, slots=True)
class ReviewQueueEntry:
    queue_id: int
    match_candidate_id: int
    left_source_record_id: int
    right_source_record_id: int
    candidate_method: str
    score: float
    candidate_decision: MatchDecision
    priority: int
    status: ReviewStatus
    reviewer_note: str | None
    reviewed_at: str | None


@dataclass(frozen=True, slots=True)
class ReviewQueuePopulateResult:
    review_candidates_seen: int
    queue_entries_inserted: int
    queue_entries_unchanged: int


@dataclass(frozen=True, slots=True)
class ReviewDecisionResult:
    queue_id: int
    match_candidate_id: int
    review_status: ReviewStatus
    candidate_decision: MatchDecision
    reviewer_note: str | None
    reviewed_at: str


def review_priority(score: float) -> int:
    """Convert a candidate score into a stable lower-is-higher priority."""
    if not 0.0 <= score <= 1.0:
        raise ReviewQueueError("score must be between 0.0 and 1.0")
    return max(1, min(1000, round((1.0 - score) * 1000)))


def populate_review_queue(
    connection: sqlite3.Connection,
) -> ReviewQueuePopulateResult:
    try:
        candidates = connection.execute(
            """
            SELECT id, score
            FROM match_candidates
            WHERE decision = 'review'
            ORDER BY score DESC, id
            """
        ).fetchall()

        inserted = 0
        unchanged = 0
        with transaction(connection):
            for candidate in candidates:
                candidate_id = int(candidate["id"])
                exists = connection.execute(
                    """
                    SELECT 1
                    FROM entity_review_queue
                    WHERE match_candidate_id = ?
                    LIMIT 1
                    """,
                    (candidate_id,),
                ).fetchone()
                if exists is not None:
                    unchanged += 1
                    continue

                connection.execute(
                    """
                    INSERT INTO entity_review_queue (
                        match_candidate_id,
                        priority,
                        status
                    )
                    VALUES (?, ?, 'pending')
                    """,
                    (
                        candidate_id,
                        review_priority(float(candidate["score"])),
                    ),
                )
                inserted += 1
    except sqlite3.Error as exc:
        raise ReviewQueueError(f"Review queue population failed: {exc}") from exc

    return ReviewQueuePopulateResult(
        review_candidates_seen=len(candidates),
        queue_entries_inserted=inserted,
        queue_entries_unchanged=unchanged,
    )


def list_review_queue(
    connection: sqlite3.Connection,
    *,
    status: ReviewStatus | None = ReviewStatus.PENDING,
) -> tuple[ReviewQueueEntry, ...]:
    query = """
        SELECT
            rq.id AS queue_id,
            rq.match_candidate_id,
            rq.priority,
            rq.status,
            rq.reviewer_note,
            rq.reviewed_at,
            mc.left_source_record_id,
            mc.right_source_record_id,
            mc.candidate_method,
            mc.score,
            mc.decision AS candidate_decision
        FROM entity_review_queue AS rq
        JOIN match_candidates AS mc
          ON mc.id = rq.match_candidate_id
    """
    parameters: tuple[object, ...] = ()
    if status is not None:
        query += " WHERE rq.status = ?"
        parameters = (status.value,)
    query += " ORDER BY rq.priority ASC, mc.score DESC, rq.id ASC"

    try:
        rows = connection.execute(query, parameters).fetchall()
    except sqlite3.Error as exc:
        raise ReviewQueueError(f"Review queue listing failed: {exc}") from exc

    return tuple(
        ReviewQueueEntry(
            queue_id=int(row["queue_id"]),
            match_candidate_id=int(row["match_candidate_id"]),
            left_source_record_id=int(row["left_source_record_id"]),
            right_source_record_id=int(row["right_source_record_id"]),
            candidate_method=str(row["candidate_method"]),
            score=float(row["score"]),
            candidate_decision=MatchDecision(str(row["candidate_decision"])),
            priority=int(row["priority"]),
            status=ReviewStatus(str(row["status"])),
            reviewer_note=(
                None if row["reviewer_note"] is None else str(row["reviewer_note"])
            ),
            reviewed_at=None if row["reviewed_at"] is None else str(row["reviewed_at"]),
        )
        for row in rows
    )


def apply_review_decision(
    connection: sqlite3.Connection,
    *,
    queue_id: int,
    status: ReviewStatus,
    reviewer_note: str | None = None,
) -> ReviewDecisionResult:
    if queue_id < 1:
        raise ReviewQueueError("queue_id must be a positive integer")
    if status not in {
        ReviewStatus.APPROVED,
        ReviewStatus.REJECTED,
        ReviewStatus.DEFERRED,
    }:
        raise ReviewQueueError(
            "review decision must be approved, rejected, or deferred"
        )

    note = None
    if reviewer_note is not None:
        note = reviewer_note.strip() or None

    candidate_decision = {
        ReviewStatus.APPROVED: MatchDecision.MATCH,
        ReviewStatus.REJECTED: MatchDecision.NO_MATCH,
        ReviewStatus.DEFERRED: MatchDecision.REVIEW,
    }[status]

    try:
        with transaction(connection):
            row = connection.execute(
                """
                SELECT match_candidate_id, status
                FROM entity_review_queue
                WHERE id = ?
                """,
                (queue_id,),
            ).fetchone()
            if row is None:
                raise ReviewQueueError(f"Review queue entry not found: {queue_id}")

            current_status = ReviewStatus(str(row["status"]))
            if current_status in {ReviewStatus.APPROVED, ReviewStatus.REJECTED}:
                raise ReviewQueueError(
                    f"Review queue entry {queue_id} is already finalized "
                    f"as {current_status.value}"
                )

            candidate_id = int(row["match_candidate_id"])
            connection.execute(
                """
                UPDATE match_candidates
                SET decision = ?,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (candidate_decision.value, candidate_id),
            )
            connection.execute(
                """
                UPDATE entity_review_queue
                SET status = ?,
                    reviewer_note = ?,
                    reviewed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (status.value, note, queue_id),
            )
            updated = connection.execute(
                "SELECT reviewed_at FROM entity_review_queue WHERE id = ?",
                (queue_id,),
            ).fetchone()
            if updated is None or updated["reviewed_at"] is None:
                raise ReviewQueueError(
                    "Review decision update did not produce reviewed_at"
                )
            reviewed_at = str(updated["reviewed_at"])
    except sqlite3.Error as exc:
        raise ReviewQueueError(f"Review decision failed: {exc}") from exc

    return ReviewDecisionResult(
        queue_id=queue_id,
        match_candidate_id=candidate_id,
        review_status=status,
        candidate_decision=candidate_decision,
        reviewer_note=note,
        reviewed_at=reviewed_at,
    )
