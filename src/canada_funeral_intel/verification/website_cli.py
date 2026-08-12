from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from canada_funeral_intel.extraction.page_people import extract_website_people
from canada_funeral_intel.extraction.storage import (
    PersonObservationStorageError,
    list_page_person_observations,
)
from canada_funeral_intel.verification.batch import (
    BatchLimits,
    WebsiteBatchError,
    batch_verify,
    populate_candidates,
)
from canada_funeral_intel.verification.checks import (
    WebsiteCheckStorageError,
    insert_website_check,
    list_website_checks,
)
from canada_funeral_intel.verification.discovery import (
    WebsiteCandidateDiscoveryError,
    discover_website_candidates,
)
from canada_funeral_intel.verification.manual import (
    ManualWebsiteEvidenceError,
    import_manual_website_evidence,
)
from canada_funeral_intel.verification.models import WebsiteReviewStatus
from canada_funeral_intel.verification.page_discovery import (
    PageDiscoveryError,
    discover_website_pages,
    list_website_pages,
)
from canada_funeral_intel.verification.probe import WebsiteProbeError, probe_website
from canada_funeral_intel.verification.review import (
    WebsiteReviewError,
    apply_website_review_decision,
    list_website_review_queue,
)
from canada_funeral_intel.verification.storage import (
    WebsiteStorageError,
    list_website_candidates,
    website_candidate_evidence_summaries,
)


class WebsiteCommandError(RuntimeError):
    """Raised when a website CLI command cannot complete safely."""


def run_website_import_manual(
    connection: sqlite3.Connection,
    *,
    input_path: Path,
    source_dataset_id: int,
    dry_run: bool = False,
) -> dict[str, object]:
    try:
        result = import_manual_website_evidence(
            connection,
            input_path=input_path,
            source_dataset_id=source_dataset_id,
            dry_run=dry_run,
        )
    except ManualWebsiteEvidenceError as exc:
        raise WebsiteCommandError(str(exc)) from exc
    return {
        "import_run_id": result.import_run_id,
        "rows_seen": result.rows_seen,
        "rows_valid": result.rows_valid,
        "rows_failed": result.rows_failed,
        "candidates_inserted": result.candidates_inserted,
        "candidates_unchanged": result.candidates_unchanged,
        "evidence_inserted": result.evidence_inserted,
        "review_entries_queued": result.review_entries_queued,
        "dry_run": result.dry_run,
        "network_used": False,
    }


def run_website_discover(
    connection: sqlite3.Connection,
) -> dict[str, object]:
    try:
        result = discover_website_candidates(connection)
    except WebsiteCandidateDiscoveryError as exc:
        raise WebsiteCommandError(str(exc)) from exc

    return {
        "memberships_seen": result.memberships_seen,
        "source_records_with_website_signals": (
            result.source_records_with_website_signals
        ),
        "candidates_inserted": result.candidates_inserted,
        "candidates_unchanged": result.candidates_unchanged,
        "evidence_inserted": result.evidence_inserted,
        "review_entries_queued": result.review_entries_queued,
        "social_candidates": result.social_candidates,
        "shared_domain_candidates": result.shared_domain_candidates,
        "branch_page_candidates": result.branch_page_candidates,
        "alternate_domain_candidates": result.alternate_domain_candidates,
        "suppressed_generic_email_signals": result.suppressed_generic_email_signals,
        "source_method_counts": dict(result.source_method_counts),
    }


def run_website_populate_candidates(
    connection: sqlite3.Connection,
    *,
    entity_id: int | None = None,
    source_dataset_id: int | None = None,
    entity_limit: int = 10,
    candidate_limit: int = 1,
    dry_run: bool = False,
) -> dict[str, object]:
    try:
        return populate_candidates(
            connection,
            entity_id=entity_id,
            source_dataset_id=source_dataset_id,
            limits=BatchLimits(entity_limit=entity_limit, candidate_limit=candidate_limit),
            dry_run=dry_run,
        )
    except WebsiteBatchError as exc:
        raise WebsiteCommandError(str(exc)) from exc


def run_website_batch_verify(
    connection: sqlite3.Connection,
    *,
    allow_network: bool,
    entity_id: int | None = None,
    entity_limit: int = 10,
    candidate_limit: int = 1,
    timeout_seconds: int = 10,
    max_redirects: int = 5,
    max_retries: int = 1,
    resume_run_id: int | None = None,
    user_agent: str = "CanadaFuneralIntel/0.1",
    dry_run: bool = False,
) -> dict[str, object]:
    try:
        return batch_verify(
            connection,
            allow_network=allow_network,
            entity_id=entity_id,
            limits=BatchLimits(entity_limit, candidate_limit, timeout_seconds, max_redirects, max_retries),
            resume_run_id=resume_run_id,
            user_agent=user_agent,
            dry_run=dry_run,
        )
    except WebsiteBatchError as exc:
        raise WebsiteCommandError(str(exc)) from exc


def run_website_list(
    connection: sqlite3.Connection,
    *,
    entity_id: int | None,
) -> list[dict[str, object]]:
    try:
        rows = list_website_candidates(
            connection,
            entity_id=entity_id,
        )
    except WebsiteStorageError as exc:
        raise WebsiteCommandError(str(exc)) from exc

    summaries = website_candidate_evidence_summaries(
        connection, website_ids=tuple(row.website_id for row in rows)
    )
    domain_counts = {
        domain: int(count)
        for domain, count in connection.execute(
            "SELECT domain, COUNT(DISTINCT entity_id) FROM websites GROUP BY domain"
        ).fetchall()
    }
    review_states = {
        int(row["website_id"]): str(row["status"])
        for row in connection.execute(
            f"SELECT website_id, status FROM website_review_queue WHERE website_id IN ({','.join('?' for _ in rows)})",
            tuple(row.website_id for row in rows),
        ).fetchall()
    } if rows else {}
    names = {
        int(row["id"]): str(row["canonical_name"])
        for row in connection.execute(
            f"SELECT id, canonical_name FROM entities WHERE id IN ({','.join('?' for _ in rows)})",
            tuple(row.entity_id for row in rows),
        ).fetchall()
    } if rows else {}
    ranked = sorted(
        rows,
        key=lambda row: (
            -int(summaries.get(row.website_id, {}).get("strongest_evidence_weight", 0)),
            -int(summaries.get(row.website_id, {}).get("supporting_evidence_count", 0)),
            int(row.domain in {domain for domain, count in domain_counts.items() if count > 1}),
            row.normalized_url,
            row.entity_id,
            row.website_id,
        ),
    )
    ranks: dict[int, int] = {}
    current_entity: int | None = None
    entity_rank = 0
    for row in ranked:
        if row.entity_id != current_entity:
            current_entity = row.entity_id
            entity_rank = 1
        else:
            entity_rank += 1
        ranks[row.website_id] = entity_rank

    return [
        {
            "website_id": row.website_id,
            "entity_id": row.entity_id,
            "source_record_id": row.source_record_id,
            "url": row.url,
            "normalized_url": row.normalized_url,
            "domain": row.domain,
            "website_kind": row.website_kind.value,
            "discovery_method": row.discovery_method,
            "confidence": row.confidence,
            "status": row.status.value,
            "is_primary": row.is_primary,
            "entity_name": names.get(row.entity_id),
            "candidate_rank": ranks[row.website_id],
            **summaries.get(row.website_id, {
                "strongest_evidence": None,
                "strongest_evidence_weight": 0,
                "supporting_evidence_count": 0,
                "evidence_classes": [],
                "source_dataset_ids": [],
                "source_record_ids": [],
                "normalized_value_ids": [],
            }),
            "shared_domain": domain_counts.get(row.domain, 0) > 1,
            "review_required": review_states.get(row.website_id) == "pending",
            "review_status": review_states.get(row.website_id),
        }
        for row in ranked
    ]


def _check_payload(row: object) -> dict[str, object]:
    return {
        "check_id": row.check_id,
        "website_id": row.website_id,
        "requested_url": row.requested_url,
        "final_url": row.final_url,
        "dns_status": row.dns_status.value,
        "dns_addresses": list(row.dns_addresses),
        "tls_status": row.tls_status.value,
        "tls_expires_at": row.tls_expires_at,
        "https_status_code": row.https_status_code,
        "http_status_code": row.http_status_code,
        "redirect_count": row.redirect_count,
        "response_time_ms": row.response_time_ms,
        "content_type": row.content_type,
        "canonical_url": row.canonical_url,
        "soft_404": row.soft_404,
        "parked_or_for_sale": row.parked_or_for_sale,
        "identity_score": row.identity_score,
        "outcome": row.outcome.value,
        "error_message": row.error_message,
        "checked_at": row.checked_at,
    }


def run_website_checks(
    connection: sqlite3.Connection,
    *,
    website_id: int | None,
) -> list[dict[str, object]]:
    try:
        rows = list_website_checks(
            connection,
            website_id=website_id,
        )
    except WebsiteCheckStorageError as exc:
        raise WebsiteCommandError(str(exc)) from exc

    return [_check_payload(row) for row in rows]


def run_website_verify(
    connection: sqlite3.Connection,
    *,
    website_id: int,
    user_agent: str,
    timeout_seconds: int,
    max_redirects: int,
) -> dict[str, object]:
    if website_id < 1:
        raise WebsiteCommandError("website_id must be a positive integer")
    if max_redirects < 0:
        raise WebsiteCommandError("max_redirects must not be negative")

    try:
        row = connection.execute(
            """
            SELECT
                normalized_url,
                website_kind
            FROM websites
            WHERE id = ?
            """,
            (website_id,),
        ).fetchone()
    except sqlite3.Error as exc:
        raise WebsiteCommandError(f"Website lookup failed: {exc}") from exc

    if row is None:
        raise WebsiteCommandError(f"Website not found: {website_id}")

    try:
        entity_row = connection.execute(
            """
            SELECT e.canonical_name
            FROM websites AS w
            JOIN entities AS e
              ON e.id = w.entity_id
            WHERE w.id = ?
            """,
            (website_id,),
        ).fetchone()
    except sqlite3.Error as exc:
        raise WebsiteCommandError(f"Website entity lookup failed: {exc}") from exc

    expected_business_name = (
        None
        if entity_row is None or entity_row["canonical_name"] is None
        else str(entity_row["canonical_name"])
    )

    try:
        check = probe_website(
            website_id=website_id,
            url=str(row["normalized_url"]),
            user_agent=user_agent,
            timeout_seconds=timeout_seconds,
            max_redirects=max_redirects,
            expected_business_name=expected_business_name,
            allow_identity_mismatch=(
                str(row["website_kind"]) != "shared"
            ),
        )
        check_id = insert_website_check(connection, check)
        stored = list_website_checks(connection, website_id=website_id)
    except (WebsiteProbeError, WebsiteCheckStorageError) as exc:
        raise WebsiteCommandError(str(exc)) from exc

    record = next(
        (item for item in stored if item.check_id == check_id),
        None,
    )
    if record is None:
        raise WebsiteCommandError(
            f"Website check {check_id} could not be read after insertion"
        )

    return _check_payload(record)


def run_website_crawl(
    connection: sqlite3.Connection,
    *,
    website_id: int,
    user_agent: str,
    timeout_seconds: int,
    max_redirects: int,
    max_pages: int,
    max_depth: int,
) -> dict[str, object]:
    try:
        result = discover_website_pages(
            connection,
            website_id=website_id,
            user_agent=user_agent,
            timeout_seconds=timeout_seconds,
            max_redirects=max_redirects,
            max_pages=max_pages,
            max_depth=max_depth,
        )
    except PageDiscoveryError as exc:
        raise WebsiteCommandError(str(exc)) from exc

    return {
        "website_id": result.website_id,
        "pages_requested": result.pages_requested,
        "pages_persisted": result.pages_persisted,
        "links_seen": result.links_seen,
        "links_queued": result.links_queued,
        "excluded_links": result.excluded_links,
        "offsite_links": result.offsite_links,
        "max_pages": result.max_pages,
        "max_depth": result.max_depth,
    }


def run_website_pages(
    connection: sqlite3.Connection,
    *,
    website_id: int | None,
) -> list[dict[str, object]]:
    try:
        rows = list_website_pages(
            connection,
            website_id=website_id,
        )
    except PageDiscoveryError as exc:
        raise WebsiteCommandError(str(exc)) from exc

    return list(rows)


def run_website_extract_people(
    connection: sqlite3.Connection,
    *,
    website_id: int,
    page_id: int | None,
    user_agent: str,
    timeout_seconds: int,
    max_redirects: int,
) -> dict[str, object]:
    try:
        result = extract_website_people(
            connection,
            website_id=website_id,
            page_id=page_id,
            user_agent=user_agent,
            timeout_seconds=timeout_seconds,
            max_redirects=max_redirects,
        )
    except (RuntimeError, ValueError) as exc:
        raise WebsiteCommandError(str(exc)) from exc

    return {
        "website_id": result.website_id,
        "pages_considered": result.pages_considered,
        "pages_fetched": result.pages_fetched,
        "pages_skipped": result.pages_skipped,
        "skip_reasons": result.skip_reasons,
        "candidates_found": result.candidates_found,
        "observations_inserted": result.observations_inserted,
        "observations_unchanged": result.observations_unchanged,
        "ambiguous_observations": result.ambiguous_observations,
        "rejected_candidates": result.rejected_candidates,
        "extractor_version": result.extractor_version,
    }


def run_website_people(
    connection: sqlite3.Connection,
    *,
    website_id: int | None,
    entity_id: int | None,
    page_id: int | None,
) -> list[dict[str, object]]:
    try:
        rows = list_page_person_observations(
            connection,
            website_id=website_id,
            entity_id=entity_id,
            page_id=page_id,
        )
    except PersonObservationStorageError as exc:
        raise WebsiteCommandError(str(exc)) from exc
    return list(rows)


def run_website_review_list(
    connection: sqlite3.Connection,
    *,
    status: WebsiteReviewStatus | None,
) -> list[dict[str, object]]:
    try:
        rows = list_website_review_queue(
            connection,
            status=status,
        )
    except WebsiteReviewError as exc:
        raise WebsiteCommandError(str(exc)) from exc

    return [
        {
            "queue_id": row.queue_id,
            "website_id": row.website_id,
            "entity_id": row.entity_id,
            "url": row.url,
            "domain": row.domain,
            "website_kind": row.website_kind.value,
            "confidence": row.confidence,
            "website_status": row.website_status.value,
            "is_primary": row.is_primary,
            "priority": row.priority,
            "review_status": row.review_status.value,
            "reviewer_note": row.reviewer_note,
            "reviewed_at": row.reviewed_at,
        }
        for row in rows
    ]


def run_website_review_decide(
    connection: sqlite3.Connection,
    *,
    queue_id: int,
    status: WebsiteReviewStatus,
    reviewer_note: str | None,
) -> dict[str, object]:
    try:
        result = apply_website_review_decision(
            connection,
            queue_id=queue_id,
            status=status,
            reviewer_note=reviewer_note,
        )
    except WebsiteReviewError as exc:
        raise WebsiteCommandError(str(exc)) from exc

    return {
        "queue_id": result.queue_id,
        "website_id": result.website_id,
        "entity_id": result.entity_id,
        "review_status": result.review_status.value,
        "website_status": result.website_status.value,
        "is_primary": result.is_primary,
        "reviewer_note": result.reviewer_note,
        "reviewed_at": result.reviewed_at,
    }


def print_website_payload(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))
