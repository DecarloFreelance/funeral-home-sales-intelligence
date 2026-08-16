from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from canada_funeral_intel.verification.page_discovery import (
    is_business_fact_relevant_page,
)
from canada_funeral_intel.verification.page_fetch import record_page_fetch
from canada_funeral_intel.verification.probe import (
    HTTPProbeResult,
    WebsiteProbeError,
    probe_http,
)

from .extraction import BusinessFactPage, extract_business_facts
from .storage import store_business_facts

_ELIGIBLE_PAGE_KINDS = (
    "about",
    "history",
    "locations",
    "contact",
    "root",
    "team",
    "staff",
    "people",
    "directors",
    "professionals",
    "management",
    "personnel",
)


@dataclass(frozen=True, slots=True)
class BusinessFactPageFailure:
    page_id: int
    website_id: int
    error: str


@dataclass(frozen=True, slots=True)
class BusinessFactProcessingResult:
    pages_selected: int
    pages_attempted: int
    pages_succeeded: int
    pages_failed: int
    facts_extracted: int
    facts_inserted: int
    facts_unchanged: int
    failures: tuple[BusinessFactPageFailure, ...]


def _page_rows(
    connection: sqlite3.Connection,
    *,
    website_id: int | None,
    page_id: int | None,
) -> list[sqlite3.Row]:
    if website_id is None and page_id is None:
        raise ValueError("website_id or page_id is required")
    if website_id is not None and website_id < 1:
        raise ValueError("website_id must be positive")
    if page_id is not None and page_id < 1:
        raise ValueError("page_id must be positive")

    candidate_page_kinds = (*_ELIGIBLE_PAGE_KINDS, "other")
    conditions = [
        "wp.page_kind IN (" + ", ".join("?" for _ in candidate_page_kinds) + ")"
    ]
    parameters: list[object] = list(candidate_page_kinds)
    if website_id is not None:
        conditions.append("wp.website_id = ?")
        parameters.append(website_id)
    if page_id is not None:
        conditions.append("wp.id = ?")
        parameters.append(page_id)

    query = f"""
        SELECT
            wp.id AS page_id,
            wp.website_id,
            w.entity_id,
            wp.normalized_url,
            wp.page_kind,
            wp.path,
            wp.link_text
        FROM website_pages AS wp
        JOIN websites AS w ON w.id = wp.website_id
        WHERE {" AND ".join(conditions)}
        ORDER BY wp.website_id, wp.priority_score DESC, wp.depth, wp.id
    """
    rows = connection.execute(query, tuple(parameters)).fetchall()
    return [
        row
        for row in rows
        if row["page_kind"] in _ELIGIBLE_PAGE_KINDS
        or (
            row["page_kind"] == "other"
            and is_business_fact_relevant_page(
                str(row["path"]),
                None if row["link_text"] is None else str(row["link_text"]),
            )
        )
    ]


def extract_business_facts_from_pages(
    connection: sqlite3.Connection,
    *,
    website_id: int | None,
    page_id: int | None,
    user_agent: str,
    timeout_seconds: int,
    max_redirects: int,
) -> BusinessFactProcessingResult:
    """Re-fetch selected persisted pages and store their business facts."""
    if timeout_seconds < 1:
        raise ValueError("timeout_seconds must be positive")
    if max_redirects < 0:
        raise ValueError("max_redirects must not be negative")
    if not user_agent.strip():
        raise ValueError("user_agent must not be empty")

    rows = _page_rows(connection, website_id=website_id, page_id=page_id)
    attempted = succeeded = facts_extracted = facts_inserted = facts_unchanged = 0
    failures: list[BusinessFactPageFailure] = []

    for row in rows:
        attempted += 1
        page_url = str(row["normalized_url"])
        try:
            result = probe_http(
                page_url,
                user_agent=user_agent,
                timeout_seconds=timeout_seconds,
                max_redirects=max_redirects,
            )
        except WebsiteProbeError as exc:
            record_page_fetch(
                connection,
                website_page_id=int(row["page_id"]),
                result=HTTPProbeResult(
                    requested_url=page_url,
                    final_url=None,
                    status_code=None,
                    redirect_count=0,
                    response_time_ms=None,
                    content_type=None,
                    canonical_url=None,
                    error_message=str(exc),
                ),
            )
            # URL/probe errors are isolated to this page. Database and extraction
            # errors below are intentionally not swallowed.
            failures.append(
                BusinessFactPageFailure(
                    page_id=int(row["page_id"]),
                    website_id=int(row["website_id"]),
                    error=str(exc),
                )
            )
            continue

        record_page_fetch(
            connection,
            website_page_id=int(row["page_id"]),
            result=result,
        )
        if result.status_code is None:
            failures.append(
                BusinessFactPageFailure(
                    page_id=int(row["page_id"]),
                    website_id=int(row["website_id"]),
                    error=result.error_message or "page retrieval failed",
                )
            )
            continue

        page = BusinessFactPage(
            website_page_id=int(row["page_id"]),
            website_id=int(row["website_id"]),
            entity_id=int(row["entity_id"]),
            source_url=result.final_url or result.requested_url,
            page_kind=str(row["page_kind"]),
        )
        extracted = extract_business_facts(
            result.body,
            content_type=result.content_type,
            status_code=result.status_code,
            page=page,
        )
        stored = store_business_facts(
            connection,
            page=page,
            result=extracted,
        )
        succeeded += 1
        facts_extracted += len(extracted.candidates)
        facts_inserted += stored.inserted
        facts_unchanged += stored.unchanged

    return BusinessFactProcessingResult(
        pages_selected=len(rows),
        pages_attempted=attempted,
        pages_succeeded=succeeded,
        pages_failed=len(failures),
        facts_extracted=facts_extracted,
        facts_inserted=facts_inserted,
        facts_unchanged=facts_unchanged,
        failures=tuple(failures),
    )
