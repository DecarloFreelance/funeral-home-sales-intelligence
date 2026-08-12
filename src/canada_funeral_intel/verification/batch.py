from __future__ import annotations

import sqlite3
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from canada_funeral_intel.storage.database import transaction

from .checks import WebsiteCheck
from .discovery import discover_website_candidates
from .probe import WebsiteProbeError, probe_website

MAX_ENTITY_LIMIT = 25
MAX_CANDIDATE_LIMIT = 2
MAX_TIMEOUT = 10
MAX_REDIRECTS = 5
MAX_RETRIES = 1


class WebsiteBatchError(RuntimeError):
    """Raised when a bounded website batch cannot proceed safely."""


@dataclass(frozen=True, slots=True)
class BatchLimits:
    entity_limit: int = 10
    candidate_limit: int = 1
    timeout_seconds: int = 10
    max_redirects: int = 5
    max_retries: int = 1

    def validate(self) -> None:
        if not 1 <= self.entity_limit <= MAX_ENTITY_LIMIT:
            raise WebsiteBatchError(f"entity_limit must be between 1 and {MAX_ENTITY_LIMIT}")
        if not 1 <= self.candidate_limit <= MAX_CANDIDATE_LIMIT:
            raise WebsiteBatchError(f"candidate_limit must be between 1 and {MAX_CANDIDATE_LIMIT}")
        if not 1 <= self.timeout_seconds <= MAX_TIMEOUT:
            raise WebsiteBatchError(f"timeout_seconds must be between 1 and {MAX_TIMEOUT}")
        if not 0 <= self.max_redirects <= MAX_REDIRECTS:
            raise WebsiteBatchError(f"max_redirects must be between 0 and {MAX_REDIRECTS}")
        if not 0 <= self.max_retries <= MAX_RETRIES:
            raise WebsiteBatchError(f"max_retries must be between 0 and {MAX_RETRIES}")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _error_class(error: str | None) -> str:
    value = (error or "").casefold()
    if "non-public" in value or "policy" in value:
        return "policy_rejected"
    if "dns" in value:
        return "dns_failure"
    if "redirect" in value:
        return "redirect_limit"
    if "timeout" in value:
        return "timeout"
    if "http request failed" in value or "connection" in value:
        return "connection_error"
    return "verification_error"


def _retryable(error_class: str) -> bool:
    return error_class in {"timeout", "connection_error", "http_server_error"}


def populate_candidates(
    connection: sqlite3.Connection,
    *,
    entity_id: int | None = None,
    source_dataset_id: int | None = None,
    limits: BatchLimits | None = None,
    dry_run: bool = False,
) -> dict[str, object]:
    limits = limits or BatchLimits()
    limits.validate()
    if entity_id is not None and entity_id < 1:
        raise WebsiteBatchError("entity_id must be positive")
    if source_dataset_id is not None and source_dataset_id < 1:
        raise WebsiteBatchError("source_dataset_id must be positive")
    if dry_run:
        return {
            "mode": "offline_candidates",
            "dry_run": True,
            "network_used": False,
            "projected": True,
            "entities_examined": min(_count_entities(connection, entity_id, source_dataset_id), limits.entity_limit),
            "candidates_generated": None,
            "candidates_inserted": 0,
            "candidates_unchanged": 0,
        }
    with transaction(connection):
        cursor = connection.execute(
            """INSERT INTO website_discovery_runs
            (mode, entity_id, source_dataset_id, entity_limit, candidate_limit, timeout_seconds, max_redirects, max_retries, network_used, status)
            VALUES ('offline_candidates', ?, ?, ?, ?, ?, ?, ?, 0, 'running')""",
            (entity_id, source_dataset_id, limits.entity_limit, limits.candidate_limit, limits.timeout_seconds, limits.max_redirects, limits.max_retries),
        )
        run_id = int(cursor.lastrowid)
    try:
        result = discover_website_candidates(
            connection,
            entity_id=entity_id,
            source_dataset_id=source_dataset_id,
            entity_limit=limits.entity_limit,
            candidate_limit=limits.candidate_limit,
        )
    except Exception as exc:
        with transaction(connection):
            connection.execute("UPDATE website_discovery_runs SET status='failed', error_summary=?, completed_at=?, updated_at=? WHERE id=?", (str(exc)[:1000], _now(), _now(), run_id))
        raise
    with transaction(connection):
        connection.execute(
            """UPDATE website_discovery_runs SET status='completed', entities_examined=?, candidates_considered=?, candidates_inserted=?, candidates_unchanged=?, review_required=?, checkpoint_entity_id=?, completed_at=?, updated_at=? WHERE id=?""",
            (min(result.memberships_seen, limits.entity_limit), result.source_records_with_website_signals, result.candidates_inserted, result.candidates_unchanged, result.review_entries_queued, entity_id, _now(), _now(), run_id),
        )
    return {
        "run_id": run_id,
        "mode": "offline_candidates",
        "dry_run": False,
        "network_used": False,
        "entities_examined": min(result.memberships_seen, limits.entity_limit),
        "candidates_considered": result.source_records_with_website_signals,
        "candidates_inserted": result.candidates_inserted,
        "candidates_unchanged": result.candidates_unchanged,
        "evidence_inserted": result.evidence_inserted,
        "review_required": result.review_entries_queued,
        "invalid_inputs": _count_invalid_inputs(connection, entity_id, source_dataset_id),
        "ambiguous_inputs": result.review_entries_queued,
        "source_method_counts": dict(result.source_method_counts),
        "shared_domain_candidates": result.shared_domain_candidates,
        "social_candidates": result.social_candidates,
        "branch_page_candidates": result.branch_page_candidates,
        "alternate_domain_candidates": result.alternate_domain_candidates,
    }


def _count_entities(connection: sqlite3.Connection, entity_id: int | None, source_dataset_id: int | None) -> int:
    return int(connection.execute(
        """SELECT COUNT(DISTINCT esr.entity_id) FROM entity_source_records esr
        JOIN entities e ON e.id=esr.entity_id
        JOIN source_records sr ON sr.id=esr.source_record_id
        WHERE e.status='active' AND (? IS NULL OR e.id=?) AND (? IS NULL OR sr.source_dataset_id=?)""",
        (entity_id, entity_id, source_dataset_id, source_dataset_id),
    ).fetchone()[0])


def _count_invalid_inputs(connection: sqlite3.Connection, entity_id: int | None, source_dataset_id: int | None) -> int:
    row = connection.execute(
        """SELECT COUNT(DISTINCT sr.id) FROM source_records sr
        JOIN entity_source_records esr ON esr.source_record_id=sr.id
        JOIN entities e ON e.id=esr.entity_id
        JOIN normalized_values nv ON nv.source_record_id=sr.id
        WHERE e.status='active' AND (? IS NULL OR e.id=?) AND (? IS NULL OR sr.source_dataset_id=?)
          AND nv.field_name IN ('url','domain','email') AND nv.original_value IS NOT NULL AND nv.normalized_value IS NULL""",
        (entity_id, entity_id, source_dataset_id, source_dataset_id),
    ).fetchone()
    return int(row[0])


def batch_verify(
    connection: sqlite3.Connection,
    *,
    allow_network: bool,
    limits: BatchLimits | None = None,
    entity_id: int | None = None,
    resume_run_id: int | None = None,
    user_agent: str = "CanadaFuneralIntel/0.1",
    verifier: Callable[..., WebsiteCheck] = probe_website,
    dry_run: bool = False,
) -> dict[str, object]:
    if dry_run:
        limits = limits or BatchLimits()
        limits.validate()
        return {
            "mode": "network_verify",
            "dry_run": True,
            "network_used": False,
            "projected_candidates": len(_candidate_ids(connection, entity_id=entity_id, limits=limits)),
        }
    if not allow_network:
        raise WebsiteBatchError("network verification requires explicit --allow-network")
    limits = limits or BatchLimits()
    limits.validate()
    if resume_run_id is not None:
        return _resume_verify(connection, resume_run_id, user_agent=user_agent, limits=limits, verifier=verifier)
    with transaction(connection):
        ids = _candidate_ids(connection, entity_id=entity_id, limits=limits)
        if not ids:
            raise WebsiteBatchError("no eligible website candidates")
        cursor = connection.execute(
            """INSERT INTO website_discovery_runs
            (mode, entity_id, entity_limit, candidate_limit, timeout_seconds, max_redirects, max_retries, network_used, status)
            VALUES ('network_verify', ?, ?, ?, ?, ?, ?, 1, 'running')""",
            (entity_id, limits.entity_limit, limits.candidate_limit, limits.timeout_seconds, limits.max_redirects, limits.max_retries),
        )
        run_id = int(cursor.lastrowid)
        for website_id, current_entity in ids:
            connection.execute(
                "INSERT INTO website_discovery_run_items (run_id, website_id, entity_id, status) VALUES (?, ?, ?, 'pending')",
                (run_id, website_id, current_entity),
            )
    return _execute_verify_run(connection, run_id, user_agent=user_agent, limits=limits, verifier=verifier)


def _candidate_ids(connection: sqlite3.Connection, *, entity_id: int | None, limits: BatchLimits) -> list[tuple[int, int]]:
    rows = connection.execute(
        """SELECT w.id website_id, w.entity_id FROM websites w JOIN entities e ON e.id=w.entity_id
        WHERE e.status='active' AND w.status <> 'rejected' AND (? IS NULL OR w.entity_id=?)
        ORDER BY w.entity_id, w.confidence DESC, w.id LIMIT ?""",
        (entity_id, entity_id, limits.entity_limit * limits.candidate_limit),
    ).fetchall()
    selected: list[tuple[int, int]] = []
    counts: Counter[int] = Counter()
    for row in rows:
        current_entity = int(row["entity_id"])
        if counts[current_entity] >= limits.candidate_limit:
            continue
        selected.append((int(row["website_id"]), current_entity))
        counts[current_entity] += 1
        if len(counts) >= limits.entity_limit:
            break
    return selected


def _resume_verify(connection: sqlite3.Connection, run_id: int, *, user_agent: str, limits: BatchLimits, verifier: Callable[..., WebsiteCheck]) -> dict[str, object]:
    row = connection.execute("SELECT status FROM website_discovery_runs WHERE id=?", (run_id,)).fetchone()
    if row is None:
        raise WebsiteBatchError(f"website discovery run not found: {run_id}")
    if row["status"] == "completed":
        raise WebsiteBatchError("completed website discovery run cannot be resumed")
    stored = connection.execute("SELECT entity_limit, candidate_limit, timeout_seconds, max_redirects, max_retries FROM website_discovery_runs WHERE id=?", (run_id,)).fetchone()
    limits = BatchLimits(int(stored["entity_limit"]), int(stored["candidate_limit"]), int(stored["timeout_seconds"]), int(stored["max_redirects"]), int(stored["max_retries"]))
    with transaction(connection):
        if connection.execute("UPDATE website_discovery_runs SET status='running', updated_at=? WHERE id=? AND status='failed'", (_now(), run_id)).rowcount != 1:
            raise WebsiteBatchError("website discovery run is already running")
    return _execute_verify_run(connection, run_id, user_agent=user_agent, limits=limits, verifier=verifier)


def _execute_verify_run(connection: sqlite3.Connection, run_id: int, *, user_agent: str, limits: BatchLimits, verifier: Callable[..., WebsiteCheck]) -> dict[str, object]:
    items = connection.execute("SELECT * FROM website_discovery_run_items WHERE run_id=? ORDER BY entity_id, website_id", (run_id,)).fetchall()
    succeeded = failed = skipped = 0
    errors: Counter[str] = Counter()
    for item in items:
        if item["status"] == "completed":
            skipped += 1
            continue
        website = connection.execute("SELECT w.id,w.normalized_url,w.website_kind,e.canonical_name FROM websites w JOIN entities e ON e.id=w.entity_id WHERE w.id=?", (item["website_id"],)).fetchone()
        remaining_attempts = max(0, limits.max_retries + 1 - int(item["attempts"]))
        if remaining_attempts == 0:
            failed += 1
            continue
        for retry_index in range(remaining_attempts):
            with transaction(connection):
                connection.execute("UPDATE website_discovery_run_items SET status='running', attempts=attempts+1, updated_at=? WHERE id=? AND status IN ('pending','failed')", (_now(), item["id"]))
            try:
                check = verifier(website_id=int(website["id"]), url=str(website["normalized_url"]), user_agent=user_agent, timeout_seconds=limits.timeout_seconds, max_redirects=limits.max_redirects, expected_business_name=website["canonical_name"], allow_identity_mismatch=str(website["website_kind"]) == "shared")
                from .checks import insert_website_check
                check_id = insert_website_check(connection, check)
                status_code = check.https_status_code or check.http_status_code
                error_class = _error_class(check.error_message) if check.error_message else (
                    "http_server_error" if status_code is not None and status_code >= 500 else
                    "http_client_error" if status_code is not None and status_code >= 400 else None
                )
                error_message = check.error_message or (f"HTTP status {status_code}" if error_class else None)
                if error_class is not None and _retryable(error_class) and retry_index < limits.max_retries:
                    errors[error_class] += 1
                    with transaction(connection):
                        connection.execute("UPDATE website_discovery_run_items SET status='pending', error_class=?, error_message=?, check_id=?, updated_at=? WHERE id=?", (error_class, str(error_message)[:1000], check_id, _now(), item["id"]))
                    continue
                if error_class is not None:
                    errors[error_class] += 1
                    with transaction(connection):
                        connection.execute("UPDATE website_discovery_run_items SET status='failed', error_class=?, error_message=?, check_id=?, updated_at=? WHERE id=?", (error_class, str(error_message)[:1000], check_id, _now(), item["id"]))
                    failed += 1
                else:
                    with transaction(connection):
                        connection.execute("UPDATE website_discovery_run_items SET status='completed', check_id=?, updated_at=? WHERE id=?", (check_id, _now(), item["id"]))
                    succeeded += 1
                break
            except (WebsiteProbeError, sqlite3.Error, ValueError) as exc:
                error_class = _error_class(str(exc))
                errors[error_class] += 1
                if _retryable(error_class) and retry_index < limits.max_retries:
                    with transaction(connection):
                        connection.execute("UPDATE website_discovery_run_items SET status='pending', error_class=?, error_message=?, updated_at=? WHERE id=?", (error_class, str(exc)[:1000], _now(), item["id"]))
                    continue
                with transaction(connection):
                    connection.execute("UPDATE website_discovery_run_items SET status='failed', error_class=?, error_message=?, updated_at=? WHERE id=?", (error_class, str(exc)[:1000], _now(), item["id"]))
                failed += 1
                break
    status = "failed" if failed else "completed"
    with transaction(connection):
        connection.execute("UPDATE website_discovery_runs SET status=?, succeeded=?, failed_count=?, skipped_count=?, checkpoint_entity_id=?, error_summary=?, completed_at=?, updated_at=? WHERE id=?", (status, succeeded, failed, skipped, items[-1]["entity_id"] if items else None, "; ".join(f"{k}:{errors[k]}" for k in sorted(errors)) or None, _now(), _now(), run_id))
    return {
        "run_id": run_id, "mode": "network_verify", "status": status, "dry_run": False, "network_used": True,
        "items_considered": len(items), "succeeded": succeeded, "failed": failed, "skipped": skipped,
        "error_classes": {key: errors[key] for key in sorted(errors)},
    }
