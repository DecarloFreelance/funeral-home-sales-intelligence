from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from canada_funeral_intel.extraction.person_analysis import (
    EXTRACTOR_VERSION,
    ExtractionSkipReason,
    analyze_person_page,
    content_hash,
)
from canada_funeral_intel.extraction.storage import insert_page_person_observation
from canada_funeral_intel.normalization.scalars import normalize_url
from canada_funeral_intel.verification.content_analysis import analyze_website_content
from canada_funeral_intel.verification.page_fetch import record_page_fetch
from canada_funeral_intel.verification.probe import probe_http

_PRIMARY_PAGE_KINDS = frozenset(
    {
        "team",
        "staff",
        "people",
        "directors",
        "professionals",
        "management",
        "personnel",
        "contact",
        "locations",
    }
)
_SECONDARY_PAGE_KINDS = frozenset({"about", "root"})


@dataclass(frozen=True, slots=True)
class PageExtractionResult:
    website_id: int
    pages_considered: int
    pages_fetched: int
    pages_skipped: int
    skip_reasons: dict[str, int]
    candidates_found: int
    observations_inserted: int
    observations_unchanged: int
    ambiguous_observations: int
    rejected_candidates: int
    extractor_version: str = EXTRACTOR_VERSION


@dataclass(frozen=True, slots=True)
class _PageContext:
    page_id: int
    website_id: int
    entity_id: int
    url: str
    page_kind: str


def _record_skip(reasons: dict[str, int], reason: ExtractionSkipReason) -> None:
    reasons[reason.value] = reasons.get(reason.value, 0) + 1


def _eligible_page(page: _PageContext) -> ExtractionSkipReason | None:
    if page.page_kind not in _PRIMARY_PAGE_KINDS | _SECONDARY_PAGE_KINDS:
        return ExtractionSkipReason.NO_ROLE_CONTEXT
    return None


def extract_website_people(
    connection: sqlite3.Connection,
    *,
    website_id: int,
    user_agent: str,
    timeout_seconds: int,
    max_redirects: int,
    page_id: int | None = None,
) -> PageExtractionResult:
    if website_id < 1:
        raise ValueError("website_id must be positive")
    if timeout_seconds < 1:
        raise ValueError("timeout_seconds must be positive")
    if max_redirects < 0:
        raise ValueError("max_redirects must not be negative")
    if page_id is not None and page_id < 1:
        raise ValueError("page_id must be positive")

    query = """
        SELECT
            wp.id AS page_id,
            wp.website_id,
            w.entity_id,
            wp.normalized_url,
            wp.page_kind
        FROM website_pages AS wp
        JOIN websites AS w ON w.id = wp.website_id
        WHERE wp.website_id = ?
    """
    parameters: list[object] = [website_id]
    if page_id is not None:
        query += " AND wp.id = ?"
        parameters.append(page_id)
    query += " ORDER BY wp.priority_score DESC, wp.depth, wp.id"

    try:
        rows = connection.execute(query, tuple(parameters)).fetchall()
    except sqlite3.Error as exc:
        raise RuntimeError(f"page extraction lookup failed: {exc}") from exc

    reasons: dict[str, int] = {}
    pages_fetched = 0
    candidates_found = 0
    observations_inserted = 0
    observations_unchanged = 0
    ambiguous_observations = 0
    rejected_candidates = 0

    for row in rows:
        page = _PageContext(
            page_id=int(row["page_id"]),
            website_id=int(row["website_id"]),
            entity_id=int(row["entity_id"]),
            url=str(row["normalized_url"]),
            page_kind=str(row["page_kind"]),
        )
        skip_reason = _eligible_page(page)
        if skip_reason is not None:
            _record_skip(reasons, skip_reason)
            continue

        result = probe_http(
            page.url,
            user_agent=user_agent,
            timeout_seconds=timeout_seconds,
            max_redirects=max_redirects,
        )
        pages_fetched += 1
        record_page_fetch(
            connection,
            website_page_id=page.page_id,
            result=result,
        )
        if result.status_code is None or not 200 <= result.status_code < 300:
            _record_skip(reasons, ExtractionSkipReason.NON_SUCCESS)
            continue
        if result.content_type is None or "html" not in result.content_type.casefold():
            _record_skip(reasons, ExtractionSkipReason.NON_HTML)
            continue
        content_status = analyze_website_content(
            result.body,
            content_type=result.content_type,
            status_code=result.status_code,
            expected_business_name=None,
        )
        if content_status.soft_404 or content_status.parked_or_for_sale:
            _record_skip(reasons, ExtractionSkipReason.EXCLUDED_CONTENT)
            continue

        analysis = analyze_person_page(result.body, content_type=result.content_type)
        snapshot_hash = content_hash(result.body)
        source_url = normalize_url(result.final_url or page.url).value or page.url
        candidates_found += len(analysis.candidates)
        ambiguous_observations += analysis.ambiguous_observations
        rejected_candidates += analysis.rejected_candidates
        for candidate in analysis.candidates:
            stored = insert_page_person_observation(
                connection,
                website_page_id=page.page_id,
                website_id=page.website_id,
                entity_id=page.entity_id,
                source_url=source_url,
                content_hash=snapshot_hash,
                candidate=candidate,
            )
            if stored.inserted:
                observations_inserted += 1
            else:
                observations_unchanged += 1

    return PageExtractionResult(
        website_id=website_id,
        pages_considered=len(rows),
        pages_fetched=pages_fetched,
        pages_skipped=sum(reasons.values()),
        skip_reasons=dict(sorted(reasons.items())),
        candidates_found=candidates_found,
        observations_inserted=observations_inserted,
        observations_unchanged=observations_unchanged,
        ambiguous_observations=ambiguous_observations,
        rejected_candidates=rejected_candidates,
    )
