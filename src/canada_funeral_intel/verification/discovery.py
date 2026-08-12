from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from urllib.parse import urlsplit

from canada_funeral_intel.normalization.scalars import normalize_domain, normalize_url
from canada_funeral_intel.verification.models import (
    WebsiteEvidence,
    WebsiteEvidenceType,
    WebsiteKind,
    WebsiteStatus,
)
from canada_funeral_intel.verification.storage import (
    WebsiteStorageError,
    make_website_candidate,
    queue_website_for_review,
    upsert_website_candidate,
)


class WebsiteCandidateDiscoveryError(RuntimeError):
    """Raised when offline website candidate discovery cannot complete safely."""


@dataclass(frozen=True, slots=True)
class WebsiteCandidateDiscoveryRun:
    memberships_seen: int
    source_records_with_website_signals: int
    candidates_inserted: int
    candidates_unchanged: int
    evidence_inserted: int
    review_entries_queued: int
    social_candidates: int
    shared_domain_candidates: int
    branch_page_candidates: int
    alternate_domain_candidates: int
    source_method_counts: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True, slots=True)
class _SourceWebsiteSignal:
    entity_id: int
    entity_type: str
    source_record_id: int
    provenance_url: str | None
    normalized_url: str
    domain: str
    discovery_method: str


_SOCIAL_DOMAINS = frozenset(
    {
        "facebook.com",
        "instagram.com",
        "linkedin.com",
        "tiktok.com",
        "twitter.com",
        "x.com",
        "youtube.com",
        "youtu.be",
    }
)
_DISCOVERY_METHOD = "normalized_source_record_v1"
_EMAIL_DISCOVERY_METHOD = "normalized_email_domain_v1"
_GENERIC_EMAIL_DOMAINS = frozenset(
    {
        "gmail.com",
        "mymts.net",
        "mts.net",
        "outlook.com",
        "shaw.ca",
    }
)


def discover_website_candidates(
    connection: sqlite3.Connection,
    *,
    entity_id: int | None = None,
    source_dataset_id: int | None = None,
    entity_limit: int | None = None,
    candidate_limit: int | None = None,
) -> WebsiteCandidateDiscoveryRun:
    """Create website candidates from existing normalized source-record signals only."""
    try:
        memberships_seen = int(
            connection.execute(
                """
                SELECT COUNT(DISTINCT esr.entity_id)
                FROM entity_source_records AS esr
                JOIN entities AS e ON e.id = esr.entity_id
                WHERE e.status = 'active'
                  AND (? IS NULL OR e.id = ?)
                  AND (? IS NULL OR EXISTS (
                      SELECT 1 FROM source_records filtered_sr
                      WHERE filtered_sr.id = esr.source_record_id
                        AND filtered_sr.source_dataset_id = ?
                  ))
                """,
                (entity_id, entity_id, source_dataset_id, source_dataset_id),
            ).fetchone()[0]
        )
        source_signals = _load_source_website_signals(connection, entity_id=entity_id, source_dataset_id=source_dataset_id)
        signals = (
            *source_signals,
            *_load_email_domain_signals(
                connection,
                existing_signals=source_signals,
                entity_id=entity_id,
                source_dataset_id=source_dataset_id,
            ),
        )
    except sqlite3.Error as exc:
        raise WebsiteCandidateDiscoveryError(
            f"Website candidate discovery query failed: {exc}"
        ) from exc

    shared_domains = _shared_domains(signals)
    preferred_domains = _preferred_domains(signals)
    selected: list[_SourceWebsiteSignal] = []
    per_entity: Counter[int] = Counter()
    for signal in signals:
        if entity_limit is not None and signal.entity_id not in {item.entity_id for item in signals}:
            continue
        if candidate_limit is not None and per_entity[signal.entity_id] >= candidate_limit:
            continue
        selected.append(signal)
        per_entity[signal.entity_id] += 1
    if entity_limit is not None:
        selected = [signal for signal in selected if signal.entity_id in sorted(per_entity)[:entity_limit]]
    signals = tuple(selected)

    inserted = 0
    unchanged = 0
    evidence_inserted = 0
    queued = 0
    social = 0
    shared = 0
    branch = 0
    alternate = 0

    for signal in signals:
        kind, confidence, needs_review = _classify_signal(
            signal,
            shared_domains=shared_domains,
            preferred_domains=preferred_domains,
        )

        candidate = make_website_candidate(
            entity_id=signal.entity_id,
            source_record_id=signal.source_record_id,
            url=signal.normalized_url,
            discovery_method=signal.discovery_method,
            confidence=confidence,
            website_kind=kind,
            status=(WebsiteStatus.REVIEW if needs_review else WebsiteStatus.CANDIDATE),
        )
        evidence = _candidate_evidence(signal, kind=kind)

        try:
            result = upsert_website_candidate(
                connection,
                candidate,
                evidence=evidence,
            )
            if needs_review:
                queue_website_for_review(connection, result.website_id)
        except WebsiteStorageError as exc:
            raise WebsiteCandidateDiscoveryError(str(exc)) from exc

        if result.inserted:
            inserted += 1
        else:
            unchanged += 1
        evidence_inserted += result.evidence_inserted
        queued += int(needs_review)

        social += int(kind is WebsiteKind.SOCIAL)
        shared += int(kind is WebsiteKind.SHARED)
        branch += int(kind is WebsiteKind.BRANCH)
        alternate += int(kind is WebsiteKind.ALTERNATE)

    return WebsiteCandidateDiscoveryRun(
        memberships_seen=memberships_seen,
        source_records_with_website_signals=len(signals),
        candidates_inserted=inserted,
        candidates_unchanged=unchanged,
        evidence_inserted=evidence_inserted,
        review_entries_queued=queued,
        social_candidates=social,
        shared_domain_candidates=shared,
        branch_page_candidates=branch,
        alternate_domain_candidates=alternate,
        source_method_counts=tuple(sorted(Counter(signal.discovery_method for signal in signals).items())),
    )


def _load_source_website_signals(
    connection: sqlite3.Connection,
    *,
    entity_id: int | None = None,
    source_dataset_id: int | None = None,
) -> tuple[_SourceWebsiteSignal, ...]:
    rows = connection.execute(
        """
        WITH latest AS (
            SELECT
                source_record_id,
                field_name,
                MAX(id) AS normalized_value_id
            FROM normalized_values
            WHERE field_name IN ('url', 'domain')
              AND normalized_value IS NOT NULL
            GROUP BY source_record_id, field_name
        ),
        values_by_record AS (
            SELECT
                latest.source_record_id,
                MAX(
                    CASE
                        WHEN nv.field_name = 'url' THEN nv.normalized_value
                    END
                ) AS normalized_url,
                MAX(
                    CASE
                        WHEN nv.field_name = 'domain' THEN nv.normalized_value
                    END
                ) AS normalized_domain
            FROM latest
            JOIN normalized_values AS nv
              ON nv.id = latest.normalized_value_id
            GROUP BY latest.source_record_id
        )
        SELECT
            esr.entity_id,
            e.entity_type,
            sr.id AS source_record_id,
            sr.source_url AS provenance_url,
            values_by_record.normalized_url,
            values_by_record.normalized_domain
        FROM entity_source_records AS esr
        JOIN entities AS e
          ON e.id = esr.entity_id
        JOIN source_records AS sr
          ON sr.id = esr.source_record_id
        JOIN values_by_record
          ON values_by_record.source_record_id = sr.id
        WHERE e.status = 'active'
          AND (? IS NULL OR e.id = ?)
          AND (? IS NULL OR sr.source_dataset_id = ?)
        ORDER BY esr.entity_id, sr.id
        """
        , (entity_id, entity_id, source_dataset_id, source_dataset_id)).fetchall()

    signals: list[_SourceWebsiteSignal] = []
    seen: set[tuple[int, str]] = set()

    for row in rows:
        normalized_url = _resolve_normalized_url(
            row["normalized_url"],
            row["normalized_domain"],
        )
        if normalized_url is None:
            continue

        domain_result = normalize_domain(normalized_url)
        if domain_result.value is None:
            continue

        key = (int(row["entity_id"]), normalized_url)
        if key in seen:
            continue
        seen.add(key)

        signals.append(
            _SourceWebsiteSignal(
                entity_id=int(row["entity_id"]),
                entity_type=str(row["entity_type"]),
                source_record_id=int(row["source_record_id"]),
                provenance_url=(
                    None
                    if row["provenance_url"] is None
                    else str(row["provenance_url"])
                ),
                normalized_url=normalized_url,
                domain=domain_result.value,
                discovery_method=_DISCOVERY_METHOD,
            )
        )

    return tuple(signals)


def _load_email_domain_signals(
    connection: sqlite3.Connection,
    *,
    existing_signals: tuple[_SourceWebsiteSignal, ...],
    entity_id: int | None = None,
    source_dataset_id: int | None = None,
) -> tuple[_SourceWebsiteSignal, ...]:
    rows = connection.execute(
        """
        WITH latest AS (
            SELECT
                source_record_id,
                MAX(id) AS normalized_value_id
            FROM normalized_values
            WHERE field_name = 'email'
            GROUP BY source_record_id
        )
        SELECT
            esr.entity_id,
            e.entity_type,
            sr.id AS source_record_id,
            sr.source_url AS provenance_url,
            nv.normalized_value AS normalized_email
        FROM entity_source_records AS esr
        JOIN entities AS e
          ON e.id = esr.entity_id
        JOIN source_records AS sr
          ON sr.id = esr.source_record_id
        JOIN latest
          ON latest.source_record_id = sr.id
        JOIN normalized_values AS nv
          ON nv.id = latest.normalized_value_id
        WHERE e.status = 'active'
          AND (? IS NULL OR e.id = ?)
          AND (? IS NULL OR sr.source_dataset_id = ?)
          AND nv.normalized_value IS NOT NULL
        ORDER BY esr.entity_id, sr.id
        """
        , (entity_id, entity_id, source_dataset_id, source_dataset_id)).fetchall()

    entities_with_explicit_signal = {
        signal.entity_id
        for signal in existing_signals
    }
    seen: set[tuple[int, str]] = {
        (signal.entity_id, signal.normalized_url)
        for signal in existing_signals
    }
    signals: list[_SourceWebsiteSignal] = []

    for row in rows:
        entity_id = int(row["entity_id"])
        if entity_id in entities_with_explicit_signal:
            continue

        email = str(row["normalized_email"]).strip()
        if email.count("@") != 1:
            continue

        domain_result = normalize_domain(email.rsplit("@", 1)[1])
        domain = domain_result.value
        if domain is None or domain in _GENERIC_EMAIL_DOMAINS:
            continue

        url_result = normalize_url(f"https://{domain}/")
        if url_result.value is None:
            continue

        key = (entity_id, url_result.value)
        if key in seen:
            continue
        seen.add(key)

        signals.append(
            _SourceWebsiteSignal(
                entity_id=entity_id,
                entity_type=str(row["entity_type"]),
                source_record_id=int(row["source_record_id"]),
                provenance_url=(
                    None
                    if row["provenance_url"] is None
                    else str(row["provenance_url"])
                ),
                normalized_url=url_result.value,
                domain=domain,
                discovery_method=_EMAIL_DISCOVERY_METHOD,
            )
        )

    return tuple(signals)


def _resolve_normalized_url(
    normalized_url: object,
    normalized_domain: object,
) -> str | None:
    if normalized_url is not None:
        result = normalize_url(str(normalized_url))
        return result.value

    if normalized_domain is None:
        return None

    domain = normalize_domain(str(normalized_domain))
    if domain.value is None:
        return None

    result = normalize_url(f"https://{domain.value}/")
    return result.value


def _shared_domains(
    signals: tuple[_SourceWebsiteSignal, ...],
) -> frozenset[str]:
    entities_by_domain: dict[str, set[int]] = defaultdict(set)
    for signal in signals:
        if not _is_social_domain(signal.domain):
            entities_by_domain[signal.domain].add(signal.entity_id)

    return frozenset(
        domain
        for domain, entity_ids in entities_by_domain.items()
        if len(entity_ids) > 1
    )


def _preferred_domains(
    signals: tuple[_SourceWebsiteSignal, ...],
) -> dict[int, str]:
    domains_by_entity: dict[int, list[str]] = defaultdict(list)
    for signal in signals:
        if not _is_social_domain(signal.domain):
            domains_by_entity[signal.entity_id].append(signal.domain)

    preferred: dict[int, str] = {}
    for entity_id, domains in domains_by_entity.items():
        counts = Counter(domains)
        preferred[entity_id] = min(
            counts,
            key=lambda domain: (-counts[domain], domain),
        )
    return preferred


def _classify_signal(
    signal: _SourceWebsiteSignal,
    *,
    shared_domains: frozenset[str],
    preferred_domains: dict[int, str],
) -> tuple[WebsiteKind, float, bool]:
    if signal.discovery_method == _EMAIL_DISCOVERY_METHOD:
        if signal.domain in shared_domains:
            return WebsiteKind.SHARED, 0.45, True
        return WebsiteKind.CANDIDATE, 0.65, True

    if _is_social_domain(signal.domain):
        return WebsiteKind.SOCIAL, 0.20, True

    path = urlsplit(signal.normalized_url).path or "/"
    is_branch_page = signal.entity_type == "branch" and path not in {"", "/"}

    if is_branch_page:
        return WebsiteKind.BRANCH, 0.85, False

    if signal.domain in shared_domains:
        return WebsiteKind.SHARED, 0.60, True

    preferred_domain = preferred_domains.get(signal.entity_id)
    if preferred_domain is not None and signal.domain != preferred_domain:
        return WebsiteKind.ALTERNATE, 0.55, True

    return WebsiteKind.CANDIDATE, 0.75, False


def _candidate_evidence(
    signal: _SourceWebsiteSignal,
    *,
    kind: WebsiteKind,
) -> tuple[WebsiteEvidence, ...]:
    if signal.discovery_method == _EMAIL_DISCOVERY_METHOD:
        return (
            WebsiteEvidence(
                evidence_type=WebsiteEvidenceType.DOMAIN,
                source_record_id=signal.source_record_id,
                evidence_value=signal.domain,
                contribution=0.30,
            ),
        )

    evidence = [
        WebsiteEvidence(
            evidence_type=WebsiteEvidenceType.NORMALIZED_URL,
            source_record_id=signal.source_record_id,
            evidence_value=signal.normalized_url,
            contribution=0.45,
        ),
        WebsiteEvidence(
            evidence_type=WebsiteEvidenceType.DOMAIN,
            source_record_id=signal.source_record_id,
            evidence_value=signal.domain,
            contribution=0.25,
        ),
    ]

    if signal.provenance_url is not None:
        evidence.append(
            WebsiteEvidence(
                evidence_type=WebsiteEvidenceType.SOURCE_URL,
                source_record_id=signal.source_record_id,
                evidence_value=signal.provenance_url,
                contribution=0.10,
            )
        )

    if kind is WebsiteKind.BRANCH:
        evidence.append(
            WebsiteEvidence(
                evidence_type=WebsiteEvidenceType.LOCATION,
                source_record_id=signal.source_record_id,
                evidence_value="branch-specific URL path",
                contribution=0.10,
            )
        )

    return tuple(evidence)


def _is_social_domain(domain: str) -> bool:
    normalized = domain.casefold().rstrip(".")
    return any(
        normalized == social_domain or normalized.endswith(f".{social_domain}")
        for social_domain in _SOCIAL_DOMAINS
    )
