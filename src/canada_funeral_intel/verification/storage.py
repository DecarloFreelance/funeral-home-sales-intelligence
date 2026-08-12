from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass

from canada_funeral_intel.normalization.scalars import normalize_domain, normalize_url
from canada_funeral_intel.storage.database import transaction
from canada_funeral_intel.verification.models import (
    WebsiteCandidate,
    WebsiteDiscoveryError,
    WebsiteEvidence,
    WebsiteEvidenceClass,
    WebsiteKind,
    WebsiteRecord,
    WebsiteStatus,
)


class WebsiteStorageError(RuntimeError):
    """Raised when website candidate persistence cannot complete safely."""


@dataclass(frozen=True, slots=True)
class WebsiteUpsertResult:
    website_id: int
    inserted: bool
    evidence_inserted: int


def make_website_candidate(
    *,
    entity_id: int,
    url: str,
    discovery_method: str,
    confidence: float,
    source_record_id: int | None = None,
    website_kind: WebsiteKind = WebsiteKind.CANDIDATE,
    status: WebsiteStatus = WebsiteStatus.CANDIDATE,
    is_primary: bool = False,
) -> WebsiteCandidate:
    normalized = normalize_url(url)
    if normalized.value is None:
        raise WebsiteDiscoveryError("url could not be normalized")

    domain = normalize_domain(normalized.value)
    if domain.value is None:
        raise WebsiteDiscoveryError("url domain could not be normalized")

    candidate = WebsiteCandidate(
        entity_id=entity_id,
        source_record_id=source_record_id,
        url=url,
        normalized_url=normalized.value,
        domain=domain.value,
        website_kind=website_kind,
        discovery_method=discovery_method,
        confidence=confidence,
        status=status,
        is_primary=is_primary,
    )
    candidate.validate()
    return candidate


def upsert_website_candidate(
    connection: sqlite3.Connection,
    candidate: WebsiteCandidate,
    *,
    evidence: tuple[WebsiteEvidence, ...] = (),
) -> WebsiteUpsertResult:
    candidate.validate()
    for item in evidence:
        item.validate()

    try:
        with transaction(connection):
            entity = connection.execute(
                "SELECT status FROM entities WHERE id = ?",
                (candidate.entity_id,),
            ).fetchone()
            if entity is None:
                raise WebsiteStorageError(f"Entity not found: {candidate.entity_id}")
            if entity["status"] != "active":
                raise WebsiteStorageError(f"Entity {candidate.entity_id} is not active")

            if candidate.source_record_id is not None:
                source = connection.execute(
                    "SELECT 1 FROM source_records WHERE id = ?",
                    (candidate.source_record_id,),
                ).fetchone()
                if source is None:
                    raise WebsiteStorageError(
                        f"Source record not found: {candidate.source_record_id}"
                    )

            existing = connection.execute(
                """
                SELECT id
                FROM websites
                WHERE entity_id = ? AND normalized_url = ?
                """,
                (candidate.entity_id, candidate.normalized_url),
            ).fetchone()

            inserted = existing is None
            if existing is None:
                cursor = connection.execute(
                    """
                    INSERT INTO websites (
                        entity_id,
                        source_record_id,
                        url,
                        normalized_url,
                        domain,
                        website_kind,
                        discovery_method,
                        confidence,
                        status,
                        is_primary
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        candidate.entity_id,
                        candidate.source_record_id,
                        candidate.url,
                        candidate.normalized_url,
                        candidate.domain,
                        candidate.website_kind.value,
                        candidate.discovery_method.strip(),
                        candidate.confidence,
                        candidate.status.value,
                        int(candidate.is_primary),
                    ),
                )
                if cursor.lastrowid is None:
                    raise WebsiteStorageError(
                        "Website candidate insert returned no row ID"
                    )
                website_id = int(cursor.lastrowid)
            else:
                website_id = int(existing["id"])
                connection.execute(
                    """
                    UPDATE websites
                    SET source_record_id = COALESCE(source_record_id, ?),
                        confidence = MAX(confidence, ?),
                        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    WHERE id = ?
                    """,
                    (
                        candidate.source_record_id,
                        candidate.confidence,
                        website_id,
                    ),
                )

            evidence_inserted = 0
            for item in evidence:
                exists = connection.execute(
                    """
                    SELECT 1
                    FROM website_evidence
                    WHERE website_id = ?
                      AND evidence_class IS ?
                      AND COALESCE(source_record_id, 0) = COALESCE(?, 0)
                      AND COALESCE(normalized_value_id, 0) = COALESCE(?, 0)
                      AND COALESCE(evidence_value, '') = COALESCE(?, '')
                    LIMIT 1
                    """,
                    (
                        website_id,
                        (item.evidence_class.value if item.evidence_class else item.evidence_type.value),
                        item.source_record_id,
                        item.normalized_value_id,
                        item.evidence_value,
                    ),
                ).fetchone()
                if exists is not None:
                    continue
                connection.execute(
                    """
                    INSERT INTO website_evidence (
                        website_id,
                        source_record_id,
                        evidence_type,
                        evidence_value,
                        contribution,
                        normalized_value_id,
                        evidence_class,
                        derivation_method,
                        derivation_version,
                        raw_value
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        website_id,
                        item.source_record_id,
                        item.evidence_type.value,
                        item.evidence_value,
                        item.contribution,
                        item.normalized_value_id,
                        (item.evidence_class.value if item.evidence_class else item.evidence_type.value),
                        item.derivation_method,
                        item.derivation_version,
                        item.raw_value or item.evidence_value,
                    ),
                )
                evidence_inserted += 1

    except sqlite3.Error as exc:
        raise WebsiteStorageError(
            f"Website candidate database operation failed: {exc}"
        ) from exc

    return WebsiteUpsertResult(
        website_id=website_id,
        inserted=inserted,
        evidence_inserted=evidence_inserted,
    )


def list_website_candidates(
    connection: sqlite3.Connection,
    *,
    entity_id: int | None = None,
) -> tuple[WebsiteRecord, ...]:
    if entity_id is not None and entity_id < 1:
        raise WebsiteStorageError("entity_id must be a positive integer")

    query = """
        SELECT
            id,
            entity_id,
            source_record_id,
            url,
            normalized_url,
            domain,
            website_kind,
            discovery_method,
            confidence,
            status,
            is_primary
        FROM websites
    """
    parameters: tuple[object, ...] = ()
    if entity_id is not None:
        query += " WHERE entity_id = ?"
        parameters = (entity_id,)
    query += " ORDER BY entity_id, confidence DESC, id"

    try:
        rows = connection.execute(query, parameters).fetchall()
    except sqlite3.Error as exc:
        raise WebsiteStorageError(f"Website candidate listing failed: {exc}") from exc

    return tuple(
        WebsiteRecord(
            website_id=int(row["id"]),
            entity_id=int(row["entity_id"]),
            source_record_id=(
                None
                if row["source_record_id"] is None
                else int(row["source_record_id"])
            ),
            url=str(row["url"]),
            normalized_url=str(row["normalized_url"]),
            domain=str(row["domain"]),
            website_kind=WebsiteKind(str(row["website_kind"])),
            discovery_method=str(row["discovery_method"]),
            confidence=float(row["confidence"]),
            status=WebsiteStatus(str(row["status"])),
            is_primary=bool(row["is_primary"]),
        )
        for row in rows
    )


def website_candidate_evidence_summaries(
    connection: sqlite3.Connection,
    *,
    website_ids: tuple[int, ...] | None = None,
) -> dict[int, dict[str, object]]:
    """Return one batched, deterministic evidence summary per website."""
    parameters: tuple[object, ...] = ()
    where = ""
    if website_ids is not None:
        if any(item < 1 for item in website_ids):
            raise WebsiteStorageError("website_ids must be positive integers")
        if not website_ids:
            return {}
        placeholders = ",".join("?" for _ in website_ids)
        where = f"WHERE we.website_id IN ({placeholders})"
        parameters = tuple(website_ids)
    rows = connection.execute(
        f"""
        SELECT we.website_id, we.evidence_class, we.evidence_type,
               we.source_record_id, we.normalized_value_id,
               sr.source_dataset_id
        FROM website_evidence AS we
        LEFT JOIN source_records AS sr ON sr.id = we.source_record_id
        {where}
        ORDER BY we.website_id, we.evidence_class, we.source_record_id,
                 we.normalized_value_id, we.evidence_value
        """,
        parameters,
    ).fetchall()
    grouped: dict[int, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        grouped[int(row["website_id"])].append(row)

    weights = {
        WebsiteEvidenceClass.EXPLICIT_SOURCE_WEBSITE.value: 700,
        WebsiteEvidenceClass.EXPLICIT_SOURCE_URL.value: 600,
        WebsiteEvidenceClass.SOURCE_DOMAIN.value: 500,
        WebsiteEvidenceClass.NORMALIZED_URL.value: 400,
        WebsiteEvidenceClass.NORMALIZED_DOMAIN.value: 300,
        WebsiteEvidenceClass.MANUAL.value: 200,
        WebsiteEvidenceClass.EMAIL_DOMAIN.value: 100,
    }
    summaries: dict[int, dict[str, object]] = {}
    for website_id, items in grouped.items():
        logical = {
            (
                row["source_record_id"],
                row["normalized_value_id"],
                row["evidence_class"] or row["evidence_type"],
            )
            for row in items
        }
        classes = sorted({str(row["evidence_class"] or row["evidence_type"]) for row in items})
        strongest = min(classes, key=lambda item: (-weights.get(item, 0), item))
        summaries[website_id] = {
            "strongest_evidence": strongest,
            "strongest_evidence_weight": weights.get(strongest, 0),
            "supporting_evidence_count": len(logical),
            "evidence_classes": classes,
            "source_dataset_ids": sorted({int(row["source_dataset_id"]) for row in items if row["source_dataset_id"] is not None}),
            "source_record_ids": sorted({int(row["source_record_id"]) for row in items if row["source_record_id"] is not None}),
            "normalized_value_ids": sorted({int(row["normalized_value_id"]) for row in items if row["normalized_value_id"] is not None}),
        }
    return summaries


def website_review_priority(confidence: float) -> int:
    if not 0.0 <= confidence <= 1.0:
        raise WebsiteStorageError("confidence must be between 0.0 and 1.0")
    return max(1, min(1000, round(abs(confidence - 0.5) * 2000)))


def queue_website_for_review(
    connection: sqlite3.Connection,
    website_id: int,
) -> int:
    if website_id < 1:
        raise WebsiteStorageError("website_id must be a positive integer")

    try:
        with transaction(connection):
            website = connection.execute(
                "SELECT confidence, status FROM websites WHERE id = ?",
                (website_id,),
            ).fetchone()
            if website is None:
                raise WebsiteStorageError(f"Website not found: {website_id}")
            if website["status"] == WebsiteStatus.REJECTED.value:
                raise WebsiteStorageError(
                    "Rejected websites cannot be queued for review"
                )

            connection.execute(
                """
                UPDATE websites
                SET status = 'review',
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (website_id,),
            )
            connection.execute(
                """
                INSERT INTO website_review_queue (website_id, priority, status)
                VALUES (?, ?, 'pending')
                ON CONFLICT(website_id) DO NOTHING
                """,
                (
                    website_id,
                    website_review_priority(float(website["confidence"])),
                ),
            )
            row = connection.execute(
                "SELECT id FROM website_review_queue WHERE website_id = ?",
                (website_id,),
            ).fetchone()
            if row is None:
                raise WebsiteStorageError("Website review queue insert returned no row")
            return int(row["id"])
    except sqlite3.Error as exc:
        raise WebsiteStorageError(
            f"Website review queue operation failed: {exc}"
        ) from exc
