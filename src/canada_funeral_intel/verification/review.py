from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from canada_funeral_intel.storage.database import transaction
from canada_funeral_intel.verification.models import (
    WebsiteKind,
    WebsiteReviewStatus,
    WebsiteStatus,
)


class WebsiteReviewError(RuntimeError):
    """Raised when website review operations cannot complete safely."""


@dataclass(frozen=True, slots=True)
class WebsiteReviewEntry:
    queue_id: int
    website_id: int
    entity_id: int
    url: str
    domain: str
    website_kind: WebsiteKind
    confidence: float
    website_status: WebsiteStatus
    is_primary: bool
    priority: int
    review_status: WebsiteReviewStatus
    reviewer_note: str | None
    reviewed_at: str | None


@dataclass(frozen=True, slots=True)
class WebsiteReviewDecisionResult:
    queue_id: int
    website_id: int
    entity_id: int
    review_status: WebsiteReviewStatus
    website_status: WebsiteStatus
    is_primary: bool
    reviewer_note: str | None
    reviewed_at: str


_CSV_COLUMNS = (
    "queue_id",
    "website_id",
    "entity_id",
    "url",
    "domain",
    "website_kind",
    "confidence",
    "priority",
    "review_status",
    "decision",
    "reviewer_note",
)


def list_website_review_queue(
    connection: sqlite3.Connection,
    *,
    status: WebsiteReviewStatus | None = WebsiteReviewStatus.PENDING,
) -> tuple[WebsiteReviewEntry, ...]:
    query = """
        SELECT
            rq.id AS queue_id,
            rq.website_id,
            rq.priority,
            rq.status AS review_status,
            rq.reviewer_note,
            rq.reviewed_at,
            w.entity_id,
            w.url,
            w.domain,
            w.website_kind,
            w.confidence,
            w.status AS website_status,
            w.is_primary
        FROM website_review_queue AS rq
        JOIN websites AS w
          ON w.id = rq.website_id
    """
    parameters: tuple[object, ...] = ()

    if status is not None:
        query += " WHERE rq.status = ?"
        parameters = (status.value,)

    query += " ORDER BY rq.priority ASC, w.confidence DESC, rq.id ASC"

    try:
        rows = connection.execute(query, parameters).fetchall()
    except sqlite3.Error as exc:
        raise WebsiteReviewError(f"Website review queue listing failed: {exc}") from exc

    return tuple(
        WebsiteReviewEntry(
            queue_id=int(row["queue_id"]),
            website_id=int(row["website_id"]),
            entity_id=int(row["entity_id"]),
            url=str(row["url"]),
            domain=str(row["domain"]),
            website_kind=WebsiteKind(str(row["website_kind"])),
            confidence=float(row["confidence"]),
            website_status=WebsiteStatus(str(row["website_status"])),
            is_primary=bool(row["is_primary"]),
            priority=int(row["priority"]),
            review_status=WebsiteReviewStatus(str(row["review_status"])),
            reviewer_note=(
                None if row["reviewer_note"] is None else str(row["reviewer_note"])
            ),
            reviewed_at=(
                None if row["reviewed_at"] is None else str(row["reviewed_at"])
            ),
        )
        for row in rows
    )


def export_website_review_csv(
    connection: sqlite3.Connection,
    *,
    output_path: Path,
    status: WebsiteReviewStatus = WebsiteReviewStatus.PENDING,
) -> dict[str, object]:
    """Export review rows for offline spreadsheet review without network access."""
    rows = list_website_review_queue(connection, status=status)
    try:
        with output_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(_CSV_COLUMNS)
            for row in rows:
                writer.writerow(
                    (
                        row.queue_id,
                        row.website_id,
                        row.entity_id,
                        row.url,
                        row.domain,
                        row.website_kind.value,
                        row.confidence,
                        row.priority,
                        row.review_status.value,
                        "",
                        row.reviewer_note or "",
                    )
                )
    except OSError as exc:
        raise WebsiteReviewError(
            f"Unable to write website review export {output_path}: {exc}"
        ) from exc
    return {
        "output_path": str(output_path),
        "rows": len(rows),
        "status": status.value,
        "network_used": False,
    }


def import_website_review_csv(
    connection: sqlite3.Connection,
    *,
    input_path: Path,
) -> dict[str, object]:
    """Validate and apply offline CSV decisions through the normal review service."""
    try:
        with input_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or not {
                "queue_id",
                "decision",
                "reviewer_note",
            }.issubset(reader.fieldnames):
                raise WebsiteReviewError(
                    "Review CSV must include queue_id, decision, and reviewer_note"
                )
            rows = list(reader)
    except OSError as exc:
        raise WebsiteReviewError(
            f"Unable to read website review import {input_path}: {exc}"
        ) from exc

    decisions: list[tuple[int, WebsiteReviewStatus, str | None]] = []
    seen: set[int] = set()
    for row_number, row in enumerate(rows, start=2):
        raw_queue_id = (row.get("queue_id") or "").strip()
        raw_decision = (row.get("decision") or "").strip().casefold()
        if not raw_queue_id and not raw_decision:
            continue
        try:
            queue_id = int(raw_queue_id)
        except ValueError as exc:
            raise WebsiteReviewError(
                f"Review CSV row {row_number} has an invalid queue_id"
            ) from exc
        if queue_id < 1 or queue_id in seen:
            raise WebsiteReviewError(
                f"Review CSV row {row_number} has a duplicate or invalid queue_id"
            )
        try:
            decision = WebsiteReviewStatus(raw_decision)
        except ValueError as exc:
            raise WebsiteReviewError(
                f"Review CSV row {row_number} has invalid decision {raw_decision!r}"
            ) from exc
        if decision not in {
            WebsiteReviewStatus.APPROVED,
            WebsiteReviewStatus.REJECTED,
            WebsiteReviewStatus.DEFERRED,
        }:
            raise WebsiteReviewError(
                f"Review CSV row {row_number} decision must be approved, rejected, or deferred"
            )
        seen.add(queue_id)
        note = (row.get("reviewer_note") or "").strip() or None
        decisions.append((queue_id, decision, note))

    applied = 0
    for queue_id, decision, note in decisions:
        apply_website_review_decision(
            connection,
            queue_id=queue_id,
            status=decision,
            reviewer_note=note,
        )
        applied += 1
    return {
        "input_path": str(input_path),
        "rows_read": len(rows),
        "decisions_applied": applied,
        "network_used": False,
    }


def apply_website_review_decision(
    connection: sqlite3.Connection,
    *,
    queue_id: int,
    status: WebsiteReviewStatus,
    reviewer_note: str | None = None,
) -> WebsiteReviewDecisionResult:
    if queue_id < 1:
        raise WebsiteReviewError("queue_id must be a positive integer")

    allowed = {
        WebsiteReviewStatus.APPROVED,
        WebsiteReviewStatus.REJECTED,
        WebsiteReviewStatus.DEFERRED,
    }
    if status not in allowed:
        raise WebsiteReviewError(
            "website review decision must be approved, rejected, or deferred"
        )

    note = None
    if reviewer_note is not None:
        note = reviewer_note.strip() or None

    try:
        with transaction(connection):
            row = connection.execute(
                """
                SELECT
                    rq.website_id,
                    rq.status AS review_status,
                    w.entity_id,
                    w.website_kind
                FROM website_review_queue AS rq
                JOIN websites AS w
                  ON w.id = rq.website_id
                WHERE rq.id = ?
                """,
                (queue_id,),
            ).fetchone()

            if row is None:
                raise WebsiteReviewError(
                    f"Website review queue entry not found: {queue_id}"
                )

            current_status = WebsiteReviewStatus(str(row["review_status"]))

            if current_status in {
                WebsiteReviewStatus.APPROVED,
                WebsiteReviewStatus.REJECTED,
            }:
                raise WebsiteReviewError(
                    f"Website review queue entry {queue_id} "
                    f"is already finalized as {current_status.value}"
                )

            website_id = int(row["website_id"])
            entity_id = int(row["entity_id"])
            website_kind = WebsiteKind(str(row["website_kind"]))

            if status is WebsiteReviewStatus.APPROVED:
                if website_kind is WebsiteKind.SOCIAL:
                    raise WebsiteReviewError(
                        "Social profiles cannot be approved as primary websites"
                    )

                existing_primary = connection.execute(
                    """
                    SELECT id
                    FROM websites
                    WHERE entity_id = ?
                      AND is_primary = 1
                      AND id != ?
                    LIMIT 1
                    """,
                    (entity_id, website_id),
                ).fetchone()

                if existing_primary is not None:
                    raise WebsiteReviewError(
                        f"Entity {entity_id} already has "
                        f"primary website "
                        f"{int(existing_primary['id'])}"
                    )

                connection.execute(
                    """
                    UPDATE websites
                    SET
                        status = 'selected',
                        is_primary = 1,
                        website_kind = CASE
                            WHEN website_kind = 'candidate'
                            THEN 'official'
                            ELSE website_kind
                        END,
                        updated_at = strftime(
                            '%Y-%m-%dT%H:%M:%fZ',
                            'now'
                        )
                    WHERE id = ?
                    """,
                    (website_id,),
                )

                website_status = WebsiteStatus.SELECTED
                is_primary = True

            elif status is WebsiteReviewStatus.REJECTED:
                connection.execute(
                    """
                    UPDATE websites
                    SET
                        status = 'rejected',
                        is_primary = 0,
                        updated_at = strftime(
                            '%Y-%m-%dT%H:%M:%fZ',
                            'now'
                        )
                    WHERE id = ?
                    """,
                    (website_id,),
                )

                website_status = WebsiteStatus.REJECTED
                is_primary = False

            else:
                connection.execute(
                    """
                    UPDATE websites
                    SET
                        status = 'review',
                        is_primary = 0,
                        updated_at = strftime(
                            '%Y-%m-%dT%H:%M:%fZ',
                            'now'
                        )
                    WHERE id = ?
                    """,
                    (website_id,),
                )

                website_status = WebsiteStatus.REVIEW
                is_primary = False

            connection.execute(
                """
                UPDATE website_review_queue
                SET
                    status = ?,
                    reviewer_note = ?,
                    reviewed_at = strftime(
                        '%Y-%m-%dT%H:%M:%fZ',
                        'now'
                    )
                WHERE id = ?
                """,
                (status.value, note, queue_id),
            )

            updated = connection.execute(
                """
                SELECT reviewed_at
                FROM website_review_queue
                WHERE id = ?
                """,
                (queue_id,),
            ).fetchone()

            if updated is None or updated["reviewed_at"] is None:
                raise WebsiteReviewError(
                    "Website review decision did not produce reviewed_at"
                )

            reviewed_at = str(updated["reviewed_at"])

    except sqlite3.IntegrityError as exc:
        raise WebsiteReviewError(
            f"Website review decision violated a database constraint: {exc}"
        ) from exc
    except sqlite3.Error as exc:
        raise WebsiteReviewError(f"Website review decision failed: {exc}") from exc

    return WebsiteReviewDecisionResult(
        queue_id=queue_id,
        website_id=website_id,
        entity_id=entity_id,
        review_status=status,
        website_status=website_status,
        is_primary=is_primary,
        reviewer_note=note,
        reviewed_at=reviewed_at,
    )


def reopen_website_review_queue(
    connection: sqlite3.Connection, *, queue_id: int, note: str | None = None
) -> None:
    """Return a finalized website to pending review after failed verification."""
    if queue_id < 1:
        raise WebsiteReviewError("queue_id must be a positive integer")
    try:
        with transaction(connection):
            row = connection.execute(
                "SELECT website_id, status FROM website_review_queue WHERE id = ?",
                (queue_id,),
            ).fetchone()
            if row is None:
                raise WebsiteReviewError(f"Website review queue entry not found: {queue_id}")
            if row["status"] not in {"approved", "deferred"}:
                raise WebsiteReviewError("Only approved or deferred website entries can be reopened")
            connection.execute(
                "UPDATE websites SET status='review', is_primary=0, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                (row["website_id"],),
            )
            connection.execute(
                "UPDATE website_review_queue SET status='pending', reviewer_note=?, reviewed_at=NULL WHERE id=?",
                (note.strip() if note and note.strip() else None, queue_id),
            )
    except sqlite3.Error as exc:
        raise WebsiteReviewError(f"Could not reopen website review entry: {exc}") from exc


def update_website_review_note(
    connection: sqlite3.Connection,
    *,
    queue_id: int,
    reviewer_note: str | None,
) -> WebsiteReviewEntry:
    """Update review evidence without changing the existing decision."""
    if queue_id < 1:
        raise WebsiteReviewError("queue_id must be a positive integer")
    note = reviewer_note.strip() if reviewer_note is not None else None
    note = note or None

    try:
        with transaction(connection):
            connection.execute(
                """
                UPDATE website_review_queue
                SET reviewer_note = ?
                WHERE id = ?
                """,
                (note, queue_id),
            )
            row = connection.execute(
                """
                SELECT
                    rq.id AS queue_id,
                    rq.website_id,
                    rq.priority,
                    rq.status AS review_status,
                    rq.reviewer_note,
                    rq.reviewed_at,
                    w.entity_id,
                    w.url,
                    w.domain,
                    w.website_kind,
                    w.confidence,
                    w.status AS website_status,
                    w.is_primary
                FROM website_review_queue AS rq
                JOIN websites AS w ON w.id = rq.website_id
                WHERE rq.id = ?
                """,
                (queue_id,),
            ).fetchone()
            if row is None:
                raise WebsiteReviewError(
                    f"Website review queue entry not found: {queue_id}"
                )
    except sqlite3.Error as exc:
        raise WebsiteReviewError(f"Website review note update failed: {exc}") from exc

    return WebsiteReviewEntry(
        queue_id=int(row["queue_id"]),
        website_id=int(row["website_id"]),
        entity_id=int(row["entity_id"]),
        url=str(row["url"]),
        domain=str(row["domain"]),
        website_kind=WebsiteKind(str(row["website_kind"])),
        confidence=float(row["confidence"]),
        website_status=WebsiteStatus(str(row["website_status"])),
        is_primary=bool(row["is_primary"]),
        priority=int(row["priority"]),
        review_status=WebsiteReviewStatus(str(row["review_status"])),
        reviewer_note=None if row["reviewer_note"] is None else str(row["reviewer_note"]),
        reviewed_at=None if row["reviewed_at"] is None else str(row["reviewed_at"]),
    )
