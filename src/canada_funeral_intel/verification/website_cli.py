from __future__ import annotations

import hashlib
import json
import sqlite3
import webbrowser
from collections.abc import Callable
from pathlib import Path

from canada_funeral_intel.extraction.page_people import extract_website_people
from canada_funeral_intel.extraction.storage import (
    PersonObservationStorageError,
    list_page_person_observations,
)
from canada_funeral_intel.storage.database import transaction
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
    export_manual_website_template,
    import_manual_website_evidence,
)
from canada_funeral_intel.verification.models import (
    WebsiteEvidence,
    WebsiteEvidenceClass,
    WebsiteEvidenceType,
    WebsiteReviewStatus,
)
from canada_funeral_intel.verification.page_discovery import (
    PageDiscoveryError,
    discover_website_pages,
    list_website_pages,
)
from canada_funeral_intel.verification.playwright_probe import (
    PlaywrightHTTPProbe,
    PlaywrightProbeError,
)
from canada_funeral_intel.verification.probe import WebsiteProbeError, probe_website
from canada_funeral_intel.verification.review import (
    WebsiteReviewError,
    apply_website_review_decision,
    export_website_review_csv,
    import_website_review_csv,
    list_website_review_queue,
    update_website_review_note,
)
from canada_funeral_intel.verification.storage import (
    WebsiteStorageError,
    list_website_candidates,
    make_website_candidate,
    queue_website_for_review,
    upsert_website_candidate,
    website_candidate_evidence_summaries,
)


class WebsiteCommandError(RuntimeError):
    """Raised when a website CLI command cannot complete safely."""


def _read_reviewer_note(input_fn: Callable[[str], str]) -> str | None:
    """Read a paste-friendly note, ending when the operator enters a blank line."""
    lines: list[str] = []
    first = input_fn(
        "Reviewer note (paste multiple lines, then press Enter on a blank line): "
    )
    if first.strip() == ".":
        return None
    if first.strip():
        lines.append(first.rstrip())
    while lines:
        continuation = input_fn("... ")
        if not continuation.strip() or continuation.strip() == ".":
            break
        lines.append(continuation.rstrip())
    return "\n".join(lines) or None


def run_website_review_interactive(
    connection: sqlite3.Connection,
    *,
    status: WebsiteReviewStatus | None = WebsiteReviewStatus.PENDING,
    open_browser: bool = False,
    group_domains: bool = False,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> dict[str, object]:
    """Guide an operator through website decisions without performing network work."""
    try:
        entries = list_website_review_queue(connection, status=status)
    except WebsiteReviewError as exc:
        raise WebsiteCommandError(str(exc)) from exc
    approved = rejected = deferred = skipped = errors = 0
    if group_domains:
        grouped = {}
        for entry in entries:
            grouped.setdefault((entry.domain, entry.url), []).append(entry)
        groups = tuple(grouped.values())
    else:
        groups = tuple([entry] for entry in entries)

    for position, group in enumerate(groups, start=1):
        entry = group[0]
        output_fn("")
        output_fn(f"[{position}/{len(groups)}] Website review queue")
        output_fn(f"  URL:        {entry.url}")
        output_fn(f"  Domain:     {entry.domain}")
        if len(group) == 1:
            output_fn(f"  Website ID: {entry.website_id}")
            output_fn(f"  Entity ID:  {entry.entity_id}")
        else:
            output_fn(f"  Shared by:  {len(group)} entity relationships")
            output_fn(
                "  Queue IDs:  " + ", ".join(str(item.queue_id) for item in group)
            )
            output_fn(
                "  Entities:   " + ", ".join(str(item.entity_id) for item in group)
            )
        output_fn(f"  Kind:       {entry.website_kind.value}")
        output_fn(f"  Confidence: {entry.confidence:.2f}")
        output_fn(f"  Priority:   {entry.priority}")
        output_fn(f"  Current:    {entry.website_status.value}")
        if entry.reviewer_note:
            output_fn(f"  Note:       {entry.reviewer_note}")

        if open_browser:
            webbrowser.open(entry.url, new=2)

        try:
            answer = (
                input_fn("Decision [a]pprove/[r]eject/[d]efer/[s]kip/[q]uit: ")
                .strip()
                .casefold()
            )
        except (EOFError, KeyboardInterrupt):
            output_fn("\nReview stopped; completed decisions were saved.")
            break

        if answer in {"q", "quit"}:
            break
        if answer in {"s", "skip", ""}:
            skipped += 1
            continue
        decision_map = {
            "a": WebsiteReviewStatus.APPROVED,
            "approve": WebsiteReviewStatus.APPROVED,
            "approved": WebsiteReviewStatus.APPROVED,
            "r": WebsiteReviewStatus.REJECTED,
            "reject": WebsiteReviewStatus.REJECTED,
            "rejected": WebsiteReviewStatus.REJECTED,
            "d": WebsiteReviewStatus.DEFERRED,
            "defer": WebsiteReviewStatus.DEFERRED,
            "deferred": WebsiteReviewStatus.DEFERRED,
        }
        decision = decision_map.get(answer)
        if decision is None:
            output_fn("Unrecognized decision; leaving this item unchanged.")
            skipped += 1
            continue

        note = _read_reviewer_note(input_fn)
        for item in group:
            try:
                result = run_website_review_decide(
                    connection,
                    queue_id=item.queue_id,
                    status=decision,
                    reviewer_note=note,
                )
            except WebsiteCommandError as exc:
                errors += 1
                output_fn(f"Could not save queue #{item.queue_id}: {exc}")
                continue
            if decision is WebsiteReviewStatus.APPROVED:
                approved += 1
            elif decision is WebsiteReviewStatus.REJECTED:
                rejected += 1
            else:
                deferred += 1
            output_fn(f"Saved: queue #{result['queue_id']} -> {decision.value}.")

    return {
        "reviewed": approved + rejected + deferred,
        "approved": approved,
        "rejected": rejected,
        "deferred": deferred,
        "skipped": skipped,
        "errors": errors,
        "remaining_presented": len(entries),
        "groups_presented": len(groups),
        "network_used": False,
    }


def run_website_manual_template(
    connection: sqlite3.Connection,
    *,
    output_path: Path,
    limit: int | None = None,
) -> dict[str, object]:
    try:
        return export_manual_website_template(
            connection,
            output_path=output_path,
            limit=limit,
        )
    except ManualWebsiteEvidenceError as exc:
        raise WebsiteCommandError(str(exc)) from exc


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
            limits=BatchLimits(
                entity_limit=entity_limit, candidate_limit=candidate_limit
            ),
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
    host_delay_seconds: float = 0.0,
    max_concurrency: int = 1,
    resume_run_id: int | None = None,
    user_agent: str = "CanadaFuneralIntel/0.1",
    dry_run: bool = False,
    progress: bool = False,
) -> dict[str, object]:
    try:
        return batch_verify(
            connection,
            allow_network=allow_network,
            entity_id=entity_id,
            limits=BatchLimits(
                entity_limit,
                candidate_limit,
                timeout_seconds,
                max_redirects,
                max_retries,
                host_delay_seconds,
                max_concurrency,
            ),
            resume_run_id=resume_run_id,
            user_agent=user_agent,
            dry_run=dry_run,
            progress=progress,
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
    review_states = (
        {
            int(row["website_id"]): str(row["status"])
            for row in connection.execute(
                f"SELECT website_id, status FROM website_review_queue WHERE website_id IN ({','.join('?' for _ in rows)})",
                tuple(row.website_id for row in rows),
            ).fetchall()
        }
        if rows
        else {}
    )
    names = (
        {
            int(row["id"]): str(row["canonical_name"])
            for row in connection.execute(
                f"SELECT id, canonical_name FROM entities WHERE id IN ({','.join('?' for _ in rows)})",
                tuple(row.entity_id for row in rows),
            ).fetchall()
        }
        if rows
        else {}
    )
    ranked = sorted(
        rows,
        key=lambda row: (
            -int(summaries.get(row.website_id, {}).get("strongest_evidence_weight", 0)),
            -int(summaries.get(row.website_id, {}).get("supporting_evidence_count", 0)),
            int(
                row.domain
                in {domain for domain, count in domain_counts.items() if count > 1}
            ),
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
            **summaries.get(
                row.website_id,
                {
                    "strongest_evidence": None,
                    "strongest_evidence_weight": 0,
                    "supporting_evidence_count": 0,
                    "evidence_classes": [],
                    "source_dataset_ids": [],
                    "source_record_ids": [],
                    "normalized_value_ids": [],
                },
            ),
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
            allow_identity_mismatch=(str(row["website_kind"]) != "shared"),
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
    engine: str = "http",
) -> dict[str, object]:
    try:
        if engine == "playwright":
            with PlaywrightHTTPProbe(
                user_agent=user_agent,
                timeout_seconds=timeout_seconds,
                max_redirects=max_redirects,
            ) as browser_probe:
                result = discover_website_pages(
                    connection,
                    website_id=website_id,
                    user_agent=user_agent,
                    timeout_seconds=timeout_seconds,
                    max_redirects=max_redirects,
                    max_pages=max_pages,
                    max_depth=max_depth,
                    probe=browser_probe,
                )
        else:
            result = discover_website_pages(
                connection,
                website_id=website_id,
                user_agent=user_agent,
                timeout_seconds=timeout_seconds,
                max_redirects=max_redirects,
                max_pages=max_pages,
                max_depth=max_depth,
            )
    except (PageDiscoveryError, PlaywrightProbeError) as exc:
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


def run_website_process_approved(
    connection: sqlite3.Connection,
    *,
    limit: int | None,
    target_website_id: int | None = None,
    user_agent: str,
    timeout_seconds: int,
    max_redirects: int,
    max_pages: int,
    max_depth: int,
    engine: str,
    fallback_playwright: bool,
) -> dict[str, object]:
    """Run the repeatable website evidence workflow for approved sites."""
    from canada_funeral_intel.business_intelligence.cli import (
        run_business_facts_extract,
    )
    from canada_funeral_intel.people.cli import run_people_review_populate

    try:
        entries = list_website_review_queue(
            connection, status=WebsiteReviewStatus.APPROVED
        )
    except WebsiteReviewError as exc:
        raise WebsiteCommandError(str(exc)) from exc

    website_ids = list(dict.fromkeys(entry.website_id for entry in entries))
    if target_website_id is not None:
        website_ids = [item for item in website_ids if item == target_website_id]
    if limit is not None:
        website_ids = website_ids[:limit]

    results: list[dict[str, object]] = []
    for website_id in website_ids:
        item: dict[str, object] = {"website_id": website_id}
        try:
            verification = run_website_verify(
                connection,
                website_id=website_id,
                user_agent=user_agent,
                timeout_seconds=timeout_seconds,
                max_redirects=max_redirects,
            )
            item["verification"] = verification
            if verification.get("outcome") != "reachable":
                item["status"] = "blocked_or_unknown"
                results.append(item)
                continue

            crawl = run_website_crawl(
                connection,
                website_id=website_id,
                user_agent=user_agent,
                timeout_seconds=timeout_seconds,
                max_redirects=max_redirects,
                max_pages=max_pages,
                max_depth=max_depth,
                engine=engine,
            )
            item["crawl"] = crawl
            effective_crawl = crawl
            if (
                fallback_playwright
                and engine == "http"
                and crawl["pages_persisted"] <= 1
            ):
                item["playwright_fallback"] = run_website_crawl(
                    connection,
                    website_id=website_id,
                    user_agent=user_agent,
                    timeout_seconds=timeout_seconds,
                    max_redirects=max_redirects,
                    max_pages=max_pages,
                    max_depth=max_depth,
                    engine="playwright",
                )
                effective_crawl = item["playwright_fallback"]

            item["people"] = run_website_extract_people(
                connection,
                website_id=website_id,
                page_id=None,
                user_agent=user_agent,
                timeout_seconds=timeout_seconds,
                max_redirects=max_redirects,
            )
            item["business_facts"] = run_business_facts_extract(
                connection,
                website_id=website_id,
                page_id=None,
                user_agent=user_agent,
                timeout_seconds=timeout_seconds,
                max_redirects=max_redirects,
            )
            item["status"] = (
                "processed"
                if effective_crawl["pages_persisted"] > 1
                else "content_limited"
            )
        except (WebsiteCommandError, ValueError, RuntimeError) as exc:
            item["status"] = "failed"
            item["error"] = str(exc)
        results.append(item)

    try:
        queue = run_people_review_populate(connection)
    except (RuntimeError, ValueError) as exc:
        raise WebsiteCommandError(str(exc)) from exc
    return {
        "approved_websites_selected": len(website_ids),
        "processed": sum(item["status"] == "processed" for item in results),
        "content_limited": sum(item["status"] == "content_limited" for item in results),
        "blocked_or_unknown": sum(
            item["status"] == "blocked_or_unknown" for item in results
        ),
        "failed": sum(item["status"] == "failed" for item in results),
        "queue": queue,
        "websites": results,
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


def run_website_review_note(
    connection: sqlite3.Connection,
    *,
    queue_id: int,
    reviewer_note: str | None,
) -> dict[str, object]:
    try:
        result = update_website_review_note(
            connection,
            queue_id=queue_id,
            reviewer_note=reviewer_note,
        )
    except WebsiteReviewError as exc:
        raise WebsiteCommandError(str(exc)) from exc
    return {
        "queue_id": result.queue_id,
        "website_id": result.website_id,
        "entity_id": result.entity_id,
        "review_status": result.review_status.value,
        "reviewer_note": result.reviewer_note,
        "reviewed_at": result.reviewed_at,
        "network_used": False,
    }


def run_website_review_export(
    connection: sqlite3.Connection,
    *,
    output_path: Path,
    status: WebsiteReviewStatus,
) -> dict[str, object]:
    try:
        return export_website_review_csv(
            connection, output_path=output_path, status=status
        )
    except WebsiteReviewError as exc:
        raise WebsiteCommandError(str(exc)) from exc


def run_website_review_import(
    connection: sqlite3.Connection,
    *,
    input_path: Path,
) -> dict[str, object]:
    try:
        return import_website_review_csv(connection, input_path=input_path)
    except WebsiteReviewError as exc:
        raise WebsiteCommandError(str(exc)) from exc


def print_website_payload(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def run_website_quality_agent(
    connection: sqlite3.Connection,
    *,
    model: str,
    provider: str,
    output: Path | None,
    keys_file: Path | None = None,
) -> dict[str, object]:
    from .agent_review import review_websites

    try:
        return review_websites(
            connection,
            model=model,
            provider=provider,
            output_path=output,
            keys_file=keys_file,
        )
    except (sqlite3.Error, ValueError, RuntimeError) as exc:
        raise WebsiteCommandError(str(exc)) from exc


def run_website_discovery_agent(
    connection: sqlite3.Connection,
    *, model: str, provider: str, output: Path | None, entity_limit: int,
) -> dict[str, object]:
    from .discovery_agent import discover_missing_websites
    try:
        return discover_missing_websites(
            connection, model=model, provider=provider, output_path=output,
            entity_limit=entity_limit,
        )
    except (sqlite3.Error, ValueError, RuntimeError) as exc:
        raise WebsiteCommandError(str(exc)) from exc


def run_website_discovery_apply(
    connection: sqlite3.Connection, *, input_path: Path, apply: bool,
) -> dict[str, object]:
    try:
        artifact = json.loads(input_path.read_text(encoding="utf-8"))
        recommendations = artifact.get("recommendations")
        if not isinstance(recommendations, list):
            raise TypeError("website-discovery artifact has no recommendations array")
        inserted = queued = skipped = 0
        for item in recommendations:
            if not isinstance(item, dict) or item.get("website_url") is None:
                skipped += 1
                continue
            if not apply:
                continue
            candidate = make_website_candidate(
                entity_id=int(item["entity_id"]), url=str(item["website_url"]),
                discovery_method="agent_discovery", confidence=float(item["confidence"]),
            )
            result = upsert_website_candidate(
                connection, candidate,
                evidence=(WebsiteEvidence(
                    evidence_type=WebsiteEvidenceType.MANUAL,
                    evidence_class=WebsiteEvidenceClass.MANUAL,
                    evidence_value=str(item.get("search_query") or "agent discovery suggestion"),
                    contribution=0.0,
                    derivation_method="website-discovery-agent-v1",
                    derivation_version="website-discovery-v1",
                ),),
            )
            inserted += int(result.inserted)
            queue_website_for_review(connection, result.website_id)
            queued += 1
        return {"applied": apply, "database_changed": bool(apply and queued),
                "recommendations": len(recommendations), "candidates_inserted": inserted,
                "review_queued": queued, "without_url": skipped}
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError, WebsiteStorageError) as exc:
        raise WebsiteCommandError(str(exc)) from exc


def run_website_candidate_review_agent(
    connection: sqlite3.Connection, *, model: str, provider: str,
    output: Path | None, queue_limit: int,
) -> dict[str, object]:
    from .candidate_review_agent import review_website_candidates
    try:
        return review_website_candidates(
            connection, model=model, provider=provider,
            output_path=output, queue_limit=queue_limit,
        )
    except (sqlite3.Error, ValueError, RuntimeError) as exc:
        raise WebsiteCommandError(str(exc)) from exc


def run_website_candidate_review_apply(
    connection: sqlite3.Connection, *, input_path: Path, apply: bool,
) -> dict[str, object]:
    try:
        artifact = json.loads(input_path.read_text(encoding="utf-8"))
        recommendations = artifact.get("recommendations")
        if not isinstance(recommendations, list):
            raise TypeError("website-candidate-review artifact has no recommendations array")
        results = {"approved": 0, "rejected": 0, "deferred": 0}
        if apply:
            for item in recommendations:
                decision = WebsiteReviewStatus(str(item["decision"]))
                apply_website_review_decision(
                    connection, queue_id=int(item["queue_id"]), status=decision,
                    reviewer_note=str(item.get("reviewer_note") or item["rationale"]),
                )
                results[decision.value] += 1
        return {"applied": apply, "database_changed": bool(apply and recommendations),
                "recommendations": len(recommendations), "decisions": results}
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError, WebsiteReviewError) as exc:
        raise WebsiteCommandError(str(exc)) from exc


def run_website_quality_apply(
    connection: sqlite3.Connection,
    *,
    input_path: Path,
    apply: bool,
) -> dict[str, object]:
    try:
        raw = input_path.read_bytes()
        artifact = json.loads(raw.decode("utf-8"))
        if not isinstance(artifact, dict) or not isinstance(
            artifact.get("recommendations"), list
        ):
            raise TypeError("website-quality artifact must contain recommendations")
        recommendations = artifact["recommendations"]
        current = {
            int(row["id"]) for row in connection.execute("SELECT id FROM websites")
        }
        seen: set[int] = set()
        for item in recommendations:
            if not isinstance(item, dict):
                raise TypeError(
                    "website-quality artifact contains a non-object recommendation"
                )
            website_id = item.get("website_id")
            if (
                isinstance(website_id, bool)
                or not isinstance(website_id, int)
                or website_id not in current
                or website_id in seen
            ):
                raise ValueError(f"invalid or duplicate website_id: {website_id}")
            if item.get("classification") not in {
                "usable",
                "limited",
                "blocked",
                "retry",
                "duplicate_shared_domain",
                "manual_lookup",
            }:
                raise ValueError(f"invalid classification for website_id {website_id}")
            if item.get("next_method") not in {
                "http",
                "playwright",
                "targeted_page",
                "manual_lookup",
                "none",
            }:
                raise ValueError(f"invalid next_method for website_id {website_id}")
            if (
                not isinstance(item.get("rationale"), str)
                or not item["rationale"].strip()
            ):
                raise ValueError(f"missing rationale for website_id {website_id}")
            seen.add(website_id)
        if seen != current:
            raise ValueError(
                f"website-quality artifact does not cover all websites; missing: {sorted(current - seen)}"
            )
        run_id = hashlib.sha256(raw).hexdigest()
        counts = {
            classification: sum(
                1
                for item in recommendations
                if item["classification"] == classification
            )
            for classification in (
                "usable",
                "limited",
                "blocked",
                "retry",
                "duplicate_shared_domain",
                "manual_lookup",
            )
        }
        result = {
            "applied": False,
            "database_changed": False,
            "artifact_sha256": run_id,
            "website_count": len(recommendations),
            "input": str(input_path),
            "run_id": run_id,
            "counts": counts,
        }
        if apply:
            with transaction(connection):
                for item in recommendations:
                    connection.execute(
                        "INSERT INTO website_quality_agent_reviews (run_id, website_id, classification, next_method, confidence, rationale, evidence_reference, provider, model, prompt_version, artifact_sha256) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            run_id,
                            item["website_id"],
                            item["classification"],
                            item["next_method"],
                            item["confidence"],
                            item["rationale"],
                            item["evidence_reference"],
                            artifact.get("provider", "unknown"),
                            artifact.get("model", "unknown"),
                            artifact.get("prompt_version", "unknown"),
                            run_id,
                        ),
                    )
            result["applied"] = True
            result["database_changed"] = True
        return result
    except (OSError, json.JSONDecodeError, sqlite3.Error, TypeError, ValueError) as exc:
        raise WebsiteCommandError(str(exc)) from exc


def run_website_quality_next_actions(
    connection: sqlite3.Connection,
    *,
    output: Path | None = None,
) -> dict[str, object]:
    rows = connection.execute(
        """
        SELECT r.website_id, w.url, r.classification, r.next_method,
               r.confidence, r.rationale, r.evidence_reference, r.run_id
        FROM website_quality_agent_reviews r
        JOIN websites w ON w.id = r.website_id
        WHERE r.id = (
            SELECT r2.id FROM website_quality_agent_reviews r2
            WHERE r2.website_id = r.website_id
            ORDER BY r2.applied_at DESC, r2.id DESC LIMIT 1
        )
        ORDER BY r.next_method, r.confidence DESC, r.website_id
        """
    ).fetchall()
    actions = [
        dict(row)
        for row in rows
        if row["classification"] != "usable" and row["next_method"] != "none"
    ]
    groups = {
        method: [row for row in actions if row["next_method"] == method]
        for method in ("http", "playwright", "targeted_page", "manual_lookup")
    }
    result = {
        "database_changed": False,
        "website_count": len(rows),
        "actionable_count": len(actions),
        "groups": groups,
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        result["output"] = str(output)
    return result


def run_website_quality_blocked_report(
    connection: sqlite3.Connection,
    *,
    output: Path | None = None,
) -> dict[str, object]:
    rows = connection.execute(
        """
        SELECT r.website_id, w.url, r.classification, r.next_method,
               r.confidence, r.rationale, r.evidence_reference, r.run_id
        FROM website_quality_agent_reviews r
        JOIN websites w ON w.id = r.website_id
        WHERE r.id = (
            SELECT r2.id FROM website_quality_agent_reviews r2
            WHERE r2.website_id = r.website_id
            ORDER BY r2.applied_at DESC, r2.id DESC LIMIT 1
        )
        AND r.classification <> 'usable'
        ORDER BY r.classification, r.next_method, r.confidence DESC, r.website_id
        """
    ).fetchall()
    items = [dict(row) for row in rows]
    groups = {
        classification: [
            item for item in items if item["classification"] == classification
        ]
        for classification in (
            "limited",
            "blocked",
            "retry",
            "duplicate_shared_domain",
            "manual_lookup",
        )
    }
    result = {
        "database_changed": False,
        "website_count": len(items),
        "groups": groups,
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        result["output"] = str(output)
    return result
