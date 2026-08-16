from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime

from canada_funeral_intel.storage.database import connect_database, transaction
from canada_funeral_intel.verification.probe import HTTPProbeResult


class PageFetchStateError(RuntimeError):
    """Raised when page-level fetch state cannot be recorded safely."""


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _content_hash(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _state_connection(
    connection: sqlite3.Connection,
) -> tuple[sqlite3.Connection, bool]:
    """Return a connection whose commit cannot affect caller-owned work."""
    if connection.in_transaction:
        raise PageFetchStateError(
            "page fetch state requires a connection without an open transaction"
        )

    database = connection.execute("PRAGMA database_list").fetchone()
    database_path = None if database is None else str(database[2])
    if not database_path:
        # SQLite in-memory databases cannot be opened independently. The
        # caller is transaction-free here, so this transaction is isolated
        # from any caller-owned work by construction.
        return connection, False
    return connect_database(database_path), True


def record_page_fetch(
    connection: sqlite3.Connection,
    *,
    website_page_id: int,
    result: HTTPProbeResult,
) -> None:
    """Record network retrieval state independently of downstream extraction."""
    if website_page_id < 1:
        raise PageFetchStateError("website_page_id must be positive")

    fetched_at = _now()
    retrieved = result.status_code is not None
    content_hash = _content_hash(result.body) if retrieved else None

    state_connection, owns_connection = _state_connection(connection)
    try:
        with transaction(state_connection):
            if retrieved:
                cursor = state_connection.execute(
                    """
                    UPDATE website_pages
                    SET last_fetched_at = ?,
                        last_success_at = ?,
                        last_status_code = ?,
                        last_content_type = ?,
                        last_error = NULL,
                        last_content_hash = ?
                    WHERE id = ?
                    """,
                    (
                        fetched_at,
                        fetched_at,
                        result.status_code,
                        result.content_type,
                        content_hash,
                        website_page_id,
                    ),
                )
            else:
                cursor = state_connection.execute(
                    """
                    UPDATE website_pages
                    SET last_fetched_at = ?,
                        last_failure_at = ?,
                        last_status_code = COALESCE(?, last_status_code),
                        last_content_type = COALESCE(?, last_content_type),
                        last_error = ?
                    WHERE id = ?
                    """,
                    (
                        fetched_at,
                        fetched_at,
                        result.status_code,
                        result.content_type,
                        result.error_message or "page retrieval failed",
                        website_page_id,
                    ),
                )

            if cursor.rowcount != 1:
                raise PageFetchStateError(f"website page not found: {website_page_id}")
    except sqlite3.Error as exc:
        raise PageFetchStateError(
            f"page fetch state persistence failed: {exc}"
        ) from exc
    finally:
        if owns_connection:
            state_connection.close()
