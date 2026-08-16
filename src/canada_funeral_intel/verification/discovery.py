from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from urllib.parse import urlsplit

from canada_funeral_intel.normalization.scalars import normalize_domain, normalize_url
from canada_funeral_intel.verification.models import (
    WebsiteEvidence,
    WebsiteEvidenceClass,
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
    suppressed_generic_email_signals: int = 0
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
    normalized_value_id: int
    evidence_class: WebsiteEvidenceClass
    raw_value: str


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
_MANUAL_DISCOVERY_METHOD = "manual_website_evidence_v1"
_EMAIL_DISCOVERY_METHOD = "normalized_email_domain_v1"
_GENERIC_EMAIL_DOMAINS = frozenset(
    {
        "gmail.com",
        "outlook.com",
        "hotmail.com",
        "icloud.com",
        "proton.me",
        "protonmail.com",
        "yahoo.com",
        "yahoo.ca",
        # Consumer / ISP mailbox domains observed in Canadian source data.
        # These domains identify the mail provider, not the funeral home's
        # authoritative web presence, so they must never seed candidates.
        "mts.net",
        "mymts.net",
        "shaw.ca",
    }
)
_GENERIC_EMAIL_POLICY_VERSION = "generic-email-domain-v2"
_EVIDENCE_WEIGHTS = {
    WebsiteEvidenceClass.EXPLICIT_SOURCE_WEBSITE: 700,
    WebsiteEvidenceClass.EXPLICIT_SOURCE_URL: 600,
    WebsiteEvidenceClass.SOURCE_DOMAIN: 500,
    WebsiteEvidenceClass.NORMALIZED_URL: 400,
    WebsiteEvidenceClass.NORMALIZED_DOMAIN: 300,
    WebsiteEvidenceClass.MANUAL: 200,
    WebsiteEvidenceClass.EMAIL_DOMAIN: 100,
}


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
        source_signals = _load_source_website_signals(
            connection, entity_id=entity_id, source_dataset_id=source_dataset_id
        )
        email_signals, suppressed_generic = _load_email_domain_signals(
            connection,
            existing_signals=source_signals,
            entity_id=entity_id,
            source_dataset_id=source_dataset_id,
        )
        signals = (*source_signals, *email_signals)
    except sqlite3.Error as exc:
        raise WebsiteCandidateDiscoveryError(
            f"Website candidate discovery query failed: {exc}"
        ) from exc

    shared_domains = _shared_domains(signals)
    explicit_urls: dict[tuple[int, str], set[str]] = defaultdict(set)
    for signal in signals:
        if signal.evidence_class in {
            WebsiteEvidenceClass.EXPLICIT_SOURCE_URL,
            WebsiteEvidenceClass.EXPLICIT_SOURCE_WEBSITE,
        }:
            explicit_urls[(signal.entity_id, signal.domain)].add(signal.normalized_url)
    remapped: list[_SourceWebsiteSignal] = []
    for signal in signals:
        targets = explicit_urls.get((signal.entity_id, signal.domain), set())
        if (
            signal.evidence_class
            not in {
                WebsiteEvidenceClass.EXPLICIT_SOURCE_URL,
                WebsiteEvidenceClass.EXPLICIT_SOURCE_WEBSITE,
            }
            and len(targets) == 1
        ):
            signal = replace(signal, normalized_url=next(iter(targets)))
        remapped.append(signal)
    signals = tuple(remapped)
    preferred_domains = _preferred_domains(signals)
    grouped: dict[tuple[int, str], list[_SourceWebsiteSignal]] = defaultdict(list)
    for signal in signals:
        grouped[(signal.entity_id, signal.normalized_url)].append(signal)
    entity_ids = sorted({entity_id for entity_id, _ in grouped})
    if entity_limit is not None:
        entity_ids = entity_ids[:entity_limit]
    selected_keys: list[tuple[int, str]] = []
    for selected_entity_id in entity_ids:
        keys = [key for key in grouped if key[0] == selected_entity_id]
        keys.sort(key=lambda key: _candidate_sort_key(key, grouped[key], shared_domains))
        selected_keys.extend(keys[:candidate_limit] if candidate_limit is not None else keys)

    inserted = 0
    unchanged = 0
    evidence_inserted = 0
    queued = 0
    social = 0
    shared = 0
    branch = 0
    alternate = 0

    for key in selected_keys:
        candidate_signals = tuple(grouped[key])
        signal = _strongest_signal(candidate_signals)
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
        evidence = _candidate_evidence(candidate_signals, kind=kind)

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
        suppressed_generic_email_signals=suppressed_generic,
        source_method_counts=tuple(sorted(Counter(signal.discovery_method for key in selected_keys for signal in grouped[key]).items())),
    )


def _load_source_website_signals(
    connection: sqlite3.Connection,
    *,
    entity_id: int | None = None,
    source_dataset_id: int | None = None,
) -> tuple[_SourceWebsiteSignal, ...]:
    rows = connection.execute(
        """
        SELECT
            esr.entity_id,
            e.entity_type,
            sr.id AS source_record_id,
            sr.source_url AS provenance_url,
            nv.id AS normalized_value_id,
            nv.field_name,
            nv.original_value,
            nv.normalized_value
        FROM entity_source_records AS esr
        JOIN entities AS e
          ON e.id = esr.entity_id
        JOIN source_records AS sr
          ON sr.id = esr.source_record_id
        JOIN normalized_values AS nv
          ON nv.source_record_id = sr.id
        WHERE e.status = 'active'
          AND (? IS NULL OR e.id = ?)
          AND (? IS NULL OR sr.source_dataset_id = ?)
          AND nv.field_name IN (
              'url', 'domain', 'explicit_website_url', 'explicit_website_domain',
              'manual_website_url'
          )
          AND nv.normalized_value IS NOT NULL
        ORDER BY esr.entity_id, sr.id, nv.id
        """, (entity_id, entity_id, source_dataset_id, source_dataset_id)).fetchall()

    signals: list[_SourceWebsiteSignal] = []
    for row in rows:
        normalized_url = _resolve_normalized_url(
            row["normalized_value"]
            if row["field_name"] in {
                "url", "explicit_website_url", "manual_website_url"
            }
            else None,
            row["normalized_value"]
            if row["field_name"] in {"domain", "explicit_website_domain"}
            else None,
        )
        if normalized_url is None:
            continue

        domain_result = normalize_domain(normalized_url)
        if domain_result.value is None:
            continue

        field_name = str(row["field_name"])
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
                discovery_method=(
                    _MANUAL_DISCOVERY_METHOD
                    if field_name == "manual_website_url"
                    else _DISCOVERY_METHOD
                ),
                normalized_value_id=int(row["normalized_value_id"]),
                evidence_class=(
                    WebsiteEvidenceClass.MANUAL
                    if field_name == "manual_website_url"
                    else (
                        WebsiteEvidenceClass.EXPLICIT_SOURCE_WEBSITE
                        if field_name.startswith("explicit_website_")
                        else (
                            WebsiteEvidenceClass.EXPLICIT_SOURCE_URL
                            if field_name == "url"
                            else WebsiteEvidenceClass.SOURCE_DOMAIN
                        )
                    )
                ),
                raw_value=str(row["original_value"] or row["normalized_value"]),
            )
        )

    return tuple(signals)


def _load_email_domain_signals(
    connection: sqlite3.Connection,
    *,
    existing_signals: tuple[_SourceWebsiteSignal, ...],
    entity_id: int | None = None,
    source_dataset_id: int | None = None,
) -> tuple[tuple[_SourceWebsiteSignal, ...], int]:
    rows = connection.execute(
        """
        SELECT
            esr.entity_id,
            e.entity_type,
            sr.id AS source_record_id,
            sr.source_url AS provenance_url,
            nv.id AS normalized_value_id,
            nv.original_value,
            nv.normalized_value AS normalized_email
        FROM entity_source_records AS esr
        JOIN entities AS e
          ON e.id = esr.entity_id
        JOIN source_records AS sr
          ON sr.id = esr.source_record_id
        JOIN normalized_values AS nv
          ON nv.source_record_id = sr.id
        WHERE e.status = 'active'
          AND (? IS NULL OR e.id = ?)
          AND (? IS NULL OR sr.source_dataset_id = ?)
          AND nv.field_name = 'email'
          AND nv.normalized_value IS NOT NULL
        ORDER BY esr.entity_id, sr.id, nv.id
        """
        , (entity_id, entity_id, source_dataset_id, source_dataset_id)).fetchall()

    signals: list[_SourceWebsiteSignal] = []
    suppressed = 0

    for row in rows:
        entity_id = int(row["entity_id"])
        email = str(row["normalized_email"]).strip()
        if email.count("@") != 1:
            continue

        domain_result = normalize_domain(email.rsplit("@", 1)[1])
        domain = domain_result.value
        if domain is None:
            continue
        if _is_generic_email_domain(domain):
            suppressed += 1
            continue

        url_result = normalize_url(f"https://{domain}/")
        if url_result.value is None:
            continue

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
                normalized_value_id=int(row["normalized_value_id"]),
                evidence_class=WebsiteEvidenceClass.EMAIL_DOMAIN,
                raw_value=str(row["original_value"] or row["normalized_email"]),
            )
        )

    return tuple(signals), suppressed


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
    if signal.evidence_class is WebsiteEvidenceClass.EMAIL_DOMAIN:
        if signal.domain in shared_domains:
            return WebsiteKind.SHARED, 0.45, True
        return WebsiteKind.CANDIDATE, 0.65, True

    if signal.evidence_class is WebsiteEvidenceClass.MANUAL:
        if signal.domain in shared_domains:
            return WebsiteKind.SHARED, 0.60, True
        if _is_social_domain(signal.domain):
            return WebsiteKind.SOCIAL, 0.20, True
        path = urlsplit(signal.normalized_url).path or "/"
        if signal.entity_type == "branch" and path not in {"", "/"}:
            return WebsiteKind.BRANCH, 0.85, True
        return WebsiteKind.CANDIDATE, 0.75, True

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
    signals: tuple[_SourceWebsiteSignal, ...],
    *,
    kind: WebsiteKind,
) -> tuple[WebsiteEvidence, ...]:
    evidence: list[WebsiteEvidence] = []
    for signal in signals:
        evidence_type = (
            WebsiteEvidenceType.NORMALIZED_URL
            if signal.evidence_class
            in {
                WebsiteEvidenceClass.EXPLICIT_SOURCE_URL,
                WebsiteEvidenceClass.EXPLICIT_SOURCE_WEBSITE,
                WebsiteEvidenceClass.MANUAL,
            }
            else WebsiteEvidenceType.DOMAIN
        )
        contribution = 0.45 if evidence_type is WebsiteEvidenceType.NORMALIZED_URL else 0.30
        evidence.append(WebsiteEvidence(
            evidence_type=evidence_type,
            evidence_class=signal.evidence_class,
            source_record_id=signal.source_record_id,
            normalized_value_id=signal.normalized_value_id,
            evidence_value=signal.normalized_url if evidence_type is WebsiteEvidenceType.NORMALIZED_URL else signal.domain,
            raw_value=signal.raw_value,
            contribution=contribution,
            derivation_method=signal.discovery_method,
        ))
        if (
            signal.provenance_url is not None
            and signal.evidence_class
            in {
                WebsiteEvidenceClass.EXPLICIT_SOURCE_URL,
                WebsiteEvidenceClass.EXPLICIT_SOURCE_WEBSITE,
            }
        ):
            evidence.append(WebsiteEvidence(
                evidence_type=WebsiteEvidenceType.SOURCE_URL,
                evidence_class=signal.evidence_class,
                source_record_id=signal.source_record_id,
                normalized_value_id=signal.normalized_value_id,
                evidence_value=signal.provenance_url,
                raw_value=signal.provenance_url,
                contribution=0.10,
                derivation_method=signal.discovery_method,
            ))
    if kind is WebsiteKind.BRANCH:
        evidence.append(WebsiteEvidence(
            evidence_type=WebsiteEvidenceType.LOCATION,
            evidence_class=WebsiteEvidenceClass.EXPLICIT_SOURCE_URL,
            evidence_value="branch-specific URL path",
            contribution=0.10,
        ))
    return tuple(evidence)


def _is_generic_email_domain(domain: str) -> bool:
    return domain in _GENERIC_EMAIL_DOMAINS or domain.endswith((".yahoo.com", ".yahoo.ca"))


def _strongest_signal(signals: tuple[_SourceWebsiteSignal, ...]) -> _SourceWebsiteSignal:
    return min(signals, key=lambda signal: (-_EVIDENCE_WEIGHTS[signal.evidence_class], signal.normalized_value_id, signal.source_record_id))


def _candidate_sort_key(
    key: tuple[int, str],
    signals: list[_SourceWebsiteSignal],
    shared_domains: frozenset[str],
) -> tuple[object, ...]:
    strongest = _strongest_signal(tuple(signals))
    source_count = len({signal.source_record_id for signal in signals})
    path_rank = int(urlsplit(key[1]).path in {"", "/"})
    return (
        -_EVIDENCE_WEIGHTS[strongest.evidence_class],
        -source_count,
        path_rank,
        int(strongest.domain in shared_domains),
        key[1],
        key[0],
    )


def _is_social_domain(domain: str) -> bool:
    normalized = domain.casefold().rstrip(".")
    return any(
        normalized == social_domain or normalized.endswith(f".{social_domain}")
        for social_domain in _SOCIAL_DOMAINS
    )
