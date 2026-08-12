from __future__ import annotations

import json
import sqlite3

from canada_funeral_intel.deduplication.review import (
    ReviewQueueError,
    ReviewStatus,
    apply_review_decision,
    list_review_queue,
    populate_review_queue,
)


class ReviewCommandError(RuntimeError):
    """Raised when a review CLI command cannot complete safely."""


def run_review_populate(connection: sqlite3.Connection) -> dict[str, object]:
    try:
        result = populate_review_queue(connection)
    except ReviewQueueError as exc:
        raise ReviewCommandError(str(exc)) from exc
    return {
        "review_candidates_seen": result.review_candidates_seen,
        "queue_entries_inserted": result.queue_entries_inserted,
        "queue_entries_unchanged": result.queue_entries_unchanged,
    }


def run_review_list(
    connection: sqlite3.Connection,
    *,
    status: ReviewStatus | None,
) -> list[dict[str, object]]:
    try:
        entries = list_review_queue(connection, status=status)
    except ReviewQueueError as exc:
        raise ReviewCommandError(str(exc)) from exc
    return [
        {
            "queue_id": entry.queue_id,
            "match_candidate_id": entry.match_candidate_id,
            "left_source_record_id": entry.left_source_record_id,
            "right_source_record_id": entry.right_source_record_id,
            "candidate_method": entry.candidate_method,
            "score": entry.score,
            "candidate_decision": entry.candidate_decision.value,
            "priority": entry.priority,
            "status": entry.status.value,
            "reviewer_note": entry.reviewer_note,
            "reviewed_at": entry.reviewed_at,
        }
        for entry in entries
    ]


def run_review_decide(
    connection: sqlite3.Connection,
    *,
    queue_id: int,
    status: ReviewStatus,
    reviewer_note: str | None,
) -> dict[str, object]:
    try:
        result = apply_review_decision(
            connection,
            queue_id=queue_id,
            status=status,
            reviewer_note=reviewer_note,
        )
    except ReviewQueueError as exc:
        raise ReviewCommandError(str(exc)) from exc
    return {
        "queue_id": result.queue_id,
        "match_candidate_id": result.match_candidate_id,
        "review_status": result.review_status.value,
        "candidate_decision": result.candidate_decision.value,
        "reviewer_note": result.reviewer_note,
        "reviewed_at": result.reviewed_at,
    }


def print_review_payload(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))
