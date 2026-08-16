from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

QUALITY_POLICY_VERSION = "quality-confidence-v1"
SUBJECT_TYPES = (
    "entity",
    "website",
    "website_page",
    "person",
    "person_observation",
    "business_fact",
)
READINESS = ("insufficient_evidence", "low", "medium", "high")

WEIGHTS: dict[str, dict[str, int]] = {
    "entity": {
        "identity_confidence": 25,
        "evidence_quality": 30,
        "provenance_quality": 25,
        "completeness": 20,
    },
    "website": {
        "identity_confidence": 35,
        "evidence_quality": 25,
        "provenance_quality": 20,
        "freshness": 20,
    },
    "website_page": {
        "identity_confidence": 35,
        "evidence_quality": 20,
        "provenance_quality": 25,
        "freshness": 20,
    },
    "person": {
        "evidence_quality": 25,
        "provenance_quality": 30,
        "consistency": 15,
        "review_confidence": 20,
        "freshness": 10,
    },
    "person_observation": {
        "evidence_quality": 35,
        "provenance_quality": 30,
        "identity_confidence": 15,
        "review_confidence": 20,
    },
    "business_fact": {
        "evidence_quality": 30,
        "provenance_quality": 30,
        "consistency": 20,
        "completeness": 10,
        "freshness": 10,
    },
}


def _clamp(value: float) -> int:
    return max(0, min(100, round(value)))


def _freshness(timestamp: str | None, reference_time: datetime) -> int | None:
    if not timestamp:
        return None
    parsed = datetime.fromisoformat(timestamp)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    age = max(
        0.0,
        (reference_time.astimezone(UTC) - parsed.astimezone(UTC)).total_seconds()
        / 86400,
    )
    return (
        100
        if age <= 30
        else 75
        if age <= 180
        else 50
        if age <= 365
        else 25
        if age <= 730
        else 0
    )


def _weighted(subject_type: str, components: dict[str, int | None]) -> float | None:
    weighted = [
        (value, WEIGHTS[subject_type][name])
        for name, value in components.items()
        if value is not None and name in WEIGHTS[subject_type]
    ]
    if not weighted:
        return None
    return round(
        sum(value * weight for value, weight in weighted)
        / sum(weight for _, weight in weighted),
        2,
    )


def _fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _result(
    subject_type: str,
    subject_id: int,
    display_name: str | None,
    components: dict[str, int | None],
    reasons: list[str],
    warnings: list[str],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    reasons = sorted(set(reasons))
    warnings = sorted(set(warnings))
    overall = _weighted(subject_type, components)
    has_evidence = bool(evidence.get("evidence_count", 0))
    readiness = (
        "insufficient_evidence"
        if overall is None or not has_evidence
        else "high"
        if overall >= 75
        else "medium"
        if overall >= 50
        else "low"
    )
    input_payload = {
        "policy_version": QUALITY_POLICY_VERSION,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "components": components,
        "evidence": evidence,
        "reasons": reasons,
        "warnings": warnings,
    }
    return {
        "subject_type": subject_type,
        "subject_id": subject_id,
        "display_name": display_name,
        "policy_version": QUALITY_POLICY_VERSION,
        "components": components,
        "overall_score": overall,
        "readiness": readiness,
        "reasons": reasons,
        "warnings": warnings,
        "evidence": evidence,
        "input_fingerprint": _fingerprint(input_payload),
    }


def _rows(
    connection: sqlite3.Connection, subject_type: str, *, include_historical: bool
) -> list[dict[str, Any]]:
    if subject_type == "entity":
        query = """
            SELECT e.id, e.canonical_name, e.status, e.entity_type,
                   COUNT(DISTINCT esr.source_record_id) AS source_count,
                   COUNT(DISTINCT w.id) AS website_count,
                   COUNT(DISTINCT bf.id) AS fact_count,
                   MAX(bf.created_at) AS latest_at
            FROM entities e
            LEFT JOIN entity_source_records esr ON esr.entity_id=e.id
            LEFT JOIN websites w ON w.entity_id=e.id
            LEFT JOIN business_fact_observations bf ON bf.entity_id=e.id
            WHERE (? OR e.status = 'active')
            GROUP BY e.id ORDER BY e.id
        """
    elif subject_type == "website":
        query = """
            SELECT w.id, e.canonical_name, w.status, w.confidence, w.website_kind,
                   w.entity_id, COUNT(DISTINCT we.id) AS evidence_count,
                   c.identity_score, c.outcome, c.checked_at
            FROM websites w JOIN entities e ON e.id=w.entity_id
            LEFT JOIN website_evidence we ON we.website_id=w.id
            LEFT JOIN website_checks c ON c.id=(SELECT c2.id FROM website_checks c2 WHERE c2.website_id=w.id ORDER BY c2.checked_at DESC,c2.id DESC LIMIT 1)
            WHERE (? OR w.status <> 'rejected')
            GROUP BY w.id ORDER BY w.id
        """
    elif subject_type == "website_page":
        query = """
            SELECT p.id, e.canonical_name, p.website_id, p.page_kind,
                   p.identity_score, p.identity_observable, p.status_code,
                   p.content_type, p.updated_at, w.entity_id,
                   COUNT(DISTINCT bf.id) AS fact_count,
                   COUNT(DISTINCT po.id) AS person_observation_count
            FROM website_pages p JOIN websites w ON w.id=p.website_id JOIN entities e ON e.id=w.entity_id
            LEFT JOIN business_fact_observations bf ON bf.website_page_id=p.id
            LEFT JOIN website_page_person_observations po ON po.website_page_id=p.id
            WHERE (? OR w.status <> 'rejected')
            GROUP BY p.id ORDER BY p.id
        """
    elif subject_type == "person":
        query = """
            SELECT p.id, p.canonical_name, p.status,
                   COUNT(DISTINCT CASE WHEN q.status='accepted' THEN pe.id END) AS evidence_count,
                   COUNT(DISTINCT CASE WHEN q.status='accepted' THEN q.id END) AS accepted_count,
                   COUNT(DISTINCT pc.id) AS contact_count,
                   COUNT(DISTINCT pa.id) AS affiliation_count,
                   COUNT(DISTINCT CASE WHEN pc.active=1 AND pc.contact_type='email' THEN pc.normalized_value END) AS email_count,
                   COUNT(DISTINCT CASE WHEN pc.active=1 AND pc.contact_type='phone' THEN pc.normalized_value END) AS phone_count,
                   COUNT(DISTINCT CASE WHEN pa.active=1 AND e.entity_type='branch' THEN pa.entity_id END) AS branch_count,
                   GROUP_CONCAT(DISTINCT CASE WHEN pa.active=1 THEN pa.entity_id END) AS entity_ids,
                   MAX(p.updated_at) AS latest_at
            FROM people p
            LEFT JOIN person_evidence pe ON pe.person_id=p.id
            LEFT JOIN website_page_person_observations o ON o.id=pe.observation_id
            LEFT JOIN person_observation_review_queue q ON q.observation_id=o.id
            LEFT JOIN person_contact_points pc ON pc.person_id=p.id AND pc.active=1
            LEFT JOIN person_affiliations pa ON pa.person_id=p.id AND pa.active=1
            LEFT JOIN entities e ON e.id=pa.entity_id
            WHERE (? OR p.status='active')
            GROUP BY p.id ORDER BY p.id
        """
    elif subject_type == "person_observation":
        query = """
            SELECT o.id, o.observed_name, o.confidence, o.website_page_id,
                   o.website_id, o.entity_id, o.email, o.phone, o.evidence_snippet,
                   o.source_url, o.content_hash, o.extractor_version, o.created_at,
                   p.identity_score, p.identity_observable, q.status AS review_status
            FROM website_page_person_observations o
            LEFT JOIN website_pages p ON p.id=o.website_page_id
            LEFT JOIN person_observation_review_queue q ON q.observation_id=o.id
            ORDER BY o.id
        """
    elif subject_type == "business_fact":
        fact_source = (
            "SELECT * FROM business_fact_observations"
            if include_historical
            else """
            SELECT bf0.* FROM business_fact_observations bf0
            JOIN (
                SELECT website_page_id, content_hash
                FROM (
                    SELECT website_page_id, content_hash, MAX(id) AS snapshot_id
                    FROM business_fact_observations
                    GROUP BY website_page_id, content_hash
                ) snapshots
                WHERE snapshot_id IN (
                    SELECT MAX(snapshot_id) FROM (
                        SELECT website_page_id, content_hash, MAX(id) AS snapshot_id
                        FROM business_fact_observations
                        GROUP BY website_page_id, content_hash
                    ) latest_per_hash GROUP BY website_page_id
                )
            ) current_hash ON current_hash.website_page_id=bf0.website_page_id AND current_hash.content_hash=bf0.content_hash
        """
        )
        query = f"""
            WITH fact_rows AS ({fact_source}), value_counts AS (
                SELECT entity_id, fact_key, scope, scope_entity_id, COUNT(DISTINCT normalized_value) AS value_count
                FROM fact_rows GROUP BY entity_id, fact_key, scope, scope_entity_id
            ), snapshot_counts AS (
                SELECT entity_id, fact_key, normalized_value, COUNT(DISTINCT website_page_id || ':' || content_hash) AS snapshot_count
                FROM fact_rows GROUP BY entity_id, fact_key, normalized_value
            )
            SELECT bf.*, p.identity_score, p.identity_observable, vc.value_count, sc.snapshot_count
            FROM fact_rows bf JOIN website_pages p ON p.id=bf.website_page_id
            JOIN websites w ON w.id=bf.website_id AND w.id=p.website_id AND w.entity_id=bf.entity_id
            JOIN entities e ON e.id=bf.entity_id
            JOIN value_counts vc ON vc.entity_id=bf.entity_id AND vc.fact_key=bf.fact_key AND vc.scope=bf.scope AND (vc.scope_entity_id IS bf.scope_entity_id)
            JOIN snapshot_counts sc ON sc.entity_id=bf.entity_id AND sc.fact_key=bf.fact_key AND sc.normalized_value=bf.normalized_value
            ORDER BY bf.id
        """
    else:
        raise ValueError(f"Unknown subject type: {subject_type}")
    return (
        [
            dict(row)
            for row in connection.execute(query, (1 if include_historical else 0,))
        ]
        if "?" in query
        else [dict(row) for row in connection.execute(query)]
    )


def _score_row(
    subject_type: str, row: dict[str, Any], reference_time: datetime
) -> dict[str, Any]:
    sid = int(row["id"])
    reasons: list[str] = []
    warnings: list[str] = []
    evidence: dict[str, Any] = {"evidence_count": 0}
    if subject_type == "entity":
        evidence = {
            "evidence_count": row["source_count"] + row["fact_count"],
            "source_count": row["source_count"],
            "website_count": row["website_count"],
            "business_fact_count": row["fact_count"],
        }
        components = {
            "identity_confidence": 75 if row["source_count"] else None,
            "evidence_quality": _clamp(min(100, evidence["evidence_count"] * 20))
            if evidence["evidence_count"]
            else None,
            "provenance_quality": 100
            if row["source_count"] or row["fact_count"]
            else None,
            "completeness": _clamp(
                (bool(row["source_count"]) * 50) + (bool(row["website_count"]) * 50)
            ),
        }
        if not row["source_count"]:
            reasons.append("missing_source_record")
    elif subject_type == "website":
        evidence = {
            "evidence_count": int(row["evidence_count"]),
            "entity_id": row["entity_id"],
            "website_kind": row["website_kind"],
            "status": row["status"],
        }
        components = {
            "identity_confidence": _clamp(
                (
                    row["identity_score"]
                    if row["identity_score"] is not None
                    else row["confidence"]
                )
                * 100
            )
            if row["identity_score"] is not None or row["confidence"] is not None
            else None,
            "evidence_quality": _clamp(min(100, row["evidence_count"] * 25))
            if row["evidence_count"]
            else None,
            "provenance_quality": 100 if row["entity_id"] is not None else None,
            "freshness": _freshness(row["checked_at"], reference_time),
        }
        if row["status"] in {"candidate", "review"}:
            reasons.append("not_review_approved")
    elif subject_type == "website_page":
        evidence = {
            "evidence_count": int(row["fact_count"] + row["person_observation_count"]),
            "website_id": row["website_id"],
            "entity_id": row["entity_id"],
            "fact_count": row["fact_count"],
            "person_observation_count": row["person_observation_count"],
        }
        components = {
            "identity_confidence": _clamp(row["identity_score"] * 100)
            if row["identity_score"] is not None and row["identity_observable"]
            else None,
            "evidence_quality": _clamp(min(100, evidence["evidence_count"] * 20))
            if evidence["evidence_count"]
            else None,
            "provenance_quality": 100
            if row["website_id"] and row["entity_id"]
            else None,
            "freshness": _freshness(row["updated_at"], reference_time),
        }
        if not row["identity_observable"]:
            warnings.append("identity_not_observable")
    elif subject_type == "person":
        evidence = {
            "evidence_count": int(row["evidence_count"]),
            "accepted_observation_count": int(row["accepted_count"]),
            "contact_count": int(row["contact_count"]),
            "affiliation_count": int(row["affiliation_count"]),
            "entity_ids": sorted(
                int(value) for value in (row["entity_ids"] or "").split(",") if value
            ),
        }
        components = {
            "evidence_quality": _clamp(min(100, row["evidence_count"] * 25))
            if row["evidence_count"]
            else None,
            "provenance_quality": 100
            if row["evidence_count"] and row["affiliation_count"]
            else (50 if row["evidence_count"] else None),
            "consistency": 0
            if row["email_count"] > 1
            or row["phone_count"] > 1
            or row["branch_count"] > 1
            else (100 if row["evidence_count"] else None),
            "review_confidence": _clamp(
                row["accepted_count"] / row["evidence_count"] * 100
            )
            if row["evidence_count"]
            else None,
            "freshness": _freshness(row["latest_at"], reference_time),
        }
        if not row["evidence_count"]:
            reasons.append("no_observation")
        if row["email_count"] > 1:
            warnings.append("conflicting_active_emails")
        if row["phone_count"] > 1:
            warnings.append("conflicting_active_phones")
        if row["branch_count"] > 1:
            warnings.append("cross_branch_unsupported")
    elif subject_type == "person_observation":
        complete = all(
            row.get(key)
            for key in (
                "website_page_id",
                "website_id",
                "entity_id",
                "source_url",
                "content_hash",
                "evidence_snippet",
                "extractor_version",
            )
        )
        evidence = {
            "evidence_count": 1,
            "observation_id": sid,
            "website_page_id": row["website_page_id"],
            "website_id": row["website_id"],
            "entity_id": row["entity_id"],
            "review_status": row["review_status"],
        }
        components = {
            "evidence_quality": _clamp(row["confidence"] * 100),
            "provenance_quality": 100 if complete else 50,
            "identity_confidence": _clamp(row["identity_score"] * 100)
            if row["identity_score"] is not None and row["identity_observable"]
            else None,
            "review_confidence": 100
            if row["review_status"] == "accepted"
            else 50
            if row["review_status"]
            else None,
        }
        if not complete:
            reasons.append("missing_provenance")
        if row["review_status"] in {"rejected", "deferred"}:
            warnings.append(f"review_{row['review_status']}")
    else:
        evidence = {
            "evidence_count": 1,
            "fact_id": sid,
            "website_page_id": row["website_page_id"],
            "website_id": row["website_id"],
            "entity_id": row["entity_id"],
            "content_hash": row["content_hash"],
            "snapshot_count": row["snapshot_count"],
            "value_count": row["value_count"],
        }
        complete = all(
            row.get(key)
            for key in (
                "website_page_id",
                "website_id",
                "entity_id",
                "source_url",
                "page_kind",
                "evidence_snippet",
                "content_hash",
                "extractor_version",
            )
        )
        distinct_bonus = min(40, max(0, int(row["snapshot_count"]) - 1) * 20)
        components = {
            "evidence_quality": _clamp(row["confidence"] * 60 + distinct_bonus),
            "provenance_quality": 100 if complete else 50,
            "consistency": 100 if row["value_count"] == 1 else 0,
            "completeness": 40 if row["scope"] == "ambiguous" else 100,
            "freshness": _freshness(row["observed_at"], reference_time),
        }
        if row["value_count"] > 1:
            warnings.append("conflicting_values")
        if row["scope"] == "ambiguous":
            warnings.append("ambiguous_scope")
        if not complete:
            reasons.append("missing_provenance")
    return _result(
        subject_type,
        sid,
        row.get("canonical_name") or row.get("observed_name") or row.get("raw_value"),
        components,
        reasons,
        warnings,
        evidence,
    )


def score_all(
    connection: sqlite3.Connection,
    subject_type: str,
    *,
    reference_time: datetime,
    include_historical: bool = False,
) -> list[dict[str, Any]]:
    if subject_type not in SUBJECT_TYPES:
        raise ValueError(f"Unknown subject type: {subject_type}")
    return [
        _score_row(subject_type, row, reference_time)
        for row in _rows(
            connection, subject_type, include_historical=include_historical
        )
    ]


def score_one(
    connection: sqlite3.Connection,
    subject_type: str,
    subject_id: int,
    *,
    reference_time: datetime,
    include_historical: bool = False,
) -> dict[str, Any]:
    rows = [
        row
        for row in score_all(
            connection,
            subject_type,
            reference_time=reference_time,
            include_historical=include_historical,
        )
        if row["subject_id"] == subject_id
    ]
    if not rows:
        raise ValueError(f"{subject_type} not found: {subject_id}")
    return rows[0]
