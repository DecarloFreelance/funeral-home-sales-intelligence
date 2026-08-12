from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from canada_funeral_intel.quality.scoring import SUBJECT_TYPES, score_all

from . import REPORT_VERSION


def _metric(metric_id: str, numerator: int, denominator: int, *, excluded: int = 0) -> dict[str, Any]:
    return {"definition_id": metric_id, "numerator": numerator, "denominator": denominator, "excluded": excluded, "percentage": round(numerator * 100 / denominator, 2) if denominator else None}


def _reference(value: datetime | None) -> str:
    now = value or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("reference time must include a timezone")
    return now.astimezone(UTC).isoformat().replace("+00:00", "Z")


def migration_version(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations").fetchone()
    return int(row["version"])


def coverage_report(connection: sqlite3.Connection, *, include_historical: bool = False, reference_time: datetime | None = None) -> dict[str, Any]:
    entity_filter = "1=1" if include_historical else "e.status = 'active'"
    person_filter = "1=1" if include_historical else "p.status = 'active'"
    row = connection.execute(f"""
        WITH eligible_entities AS (SELECT id FROM entities e WHERE {entity_filter}),
        source_entities AS (SELECT DISTINCT esr.entity_id FROM entity_source_records esr JOIN eligible_entities x ON x.id=esr.entity_id),
        website_entities AS (SELECT DISTINCT w.entity_id FROM websites w JOIN eligible_entities x ON x.id=w.entity_id WHERE {'1=1' if include_historical else "w.status <> 'rejected'"}),
        page_entities AS (SELECT DISTINCT w.entity_id FROM website_pages p JOIN websites w ON w.id=p.website_id JOIN eligible_entities x ON x.id=w.entity_id WHERE {'1=1' if include_historical else "w.status <> 'rejected'"}),
        observation_entities AS (SELECT DISTINCT o.entity_id FROM website_page_person_observations o JOIN eligible_entities x ON x.id=o.entity_id),
        people_entities AS (SELECT DISTINCT a.entity_id FROM person_affiliations a JOIN people p ON p.id=a.person_id WHERE a.active=1 AND {person_filter}),
        fact_entities AS (SELECT DISTINCT bf.entity_id FROM business_fact_observations bf JOIN eligible_entities x ON x.id=bf.entity_id),
        quality_entities AS (SELECT DISTINCT e.id FROM entities e LEFT JOIN websites w ON w.entity_id=e.id LEFT JOIN business_fact_observations bf ON bf.entity_id=e.id WHERE {entity_filter} AND (w.id IS NOT NULL OR bf.id IS NOT NULL)),
        counts AS (SELECT (SELECT COUNT(*) FROM eligible_entities) AS entity_count, (SELECT COUNT(*) FROM source_entities) AS source_count, (SELECT COUNT(*) FROM website_entities) AS website_count, (SELECT COUNT(*) FROM page_entities) AS page_count, (SELECT COUNT(*) FROM observation_entities) AS observation_count, (SELECT COUNT(*) FROM people_entities) AS people_count, (SELECT COUNT(*) FROM fact_entities) AS fact_count, (SELECT COUNT(*) FROM quality_entities) AS quality_count),
        people_counts AS (SELECT COUNT(*) AS people_count, COUNT(DISTINCT CASE WHEN c.contact_type='email' AND c.active=1 THEN c.person_id END) AS email_count, COUNT(DISTINCT CASE WHEN c.contact_type='phone' AND c.active=1 THEN c.person_id END) AS phone_count, COUNT(DISTINCT CASE WHEN q.status='accepted' THEN pe.person_id END) AS accepted_count FROM people p LEFT JOIN person_contact_points c ON c.person_id=p.id LEFT JOIN person_evidence pe ON pe.person_id=p.id LEFT JOIN person_observation_review_queue q ON q.observation_id=pe.observation_id WHERE {person_filter})
        SELECT * FROM counts CROSS JOIN people_counts
    """).fetchone()
    denominator = int(row["entity_count"])
    people_denominator = int(row["people_count"])
    entity_rows = connection.execute(f"SELECT COUNT(*) AS count, SUM(entity_type='organization') AS organizations, SUM(entity_type='branch') AS branches FROM entities e WHERE {entity_filter}").fetchone()
    metrics = [
        _metric("entities_with_source", row["source_count"], denominator),
        _metric("entities_with_website", row["website_count"], denominator),
        _metric("entities_with_page", row["page_count"], denominator),
        _metric("entities_with_people_observation", row["observation_count"], denominator),
        _metric("entities_with_canonical_person", row["people_count"], denominator),
        _metric("entities_with_business_fact", row["fact_count"], denominator),
        _metric("entities_with_quality", row["quality_count"], denominator),
        _metric("people_with_email", row["email_count"], people_denominator),
        _metric("people_with_phone", row["phone_count"], people_denominator),
        _metric("people_with_accepted_evidence", row["accepted_count"], people_denominator),
    ]
    return {"report_version": REPORT_VERSION, "reference_time": _reference(reference_time), "include_historical": include_historical, "entity_counts": {"total": int(entity_rows["count"]), "organizations": int(entity_rows["organizations"] or 0), "branches": int(entity_rows["branches"] or 0)}, "metrics": metrics}


def quality_report(connection: sqlite3.Connection, *, include_historical: bool = False, reference_time: datetime | None = None) -> dict[str, Any]:
    ref = reference_time or datetime.now(UTC)
    results = [row for subject_type in SUBJECT_TYPES for row in score_all(connection, subject_type, reference_time=ref, include_historical=include_historical)]
    results.sort(key=lambda row: (row["subject_type"], row["subject_id"]))
    distributions = {label: sum(row["readiness"] == label for row in results) for label in ("insufficient_evidence", "low", "medium", "high")}
    by_type: list[dict[str, Any]] = []
    for subject_type in SUBJECT_TYPES:
        group = [row for row in results if row["subject_type"] == subject_type]
        scores = [row["overall_score"] for row in group if row["overall_score"] is not None]
        by_type.append({"subject_type": subject_type, "count": len(group), "scored_count": len(scores), "average_score": round(sum(scores) / len(scores), 2) if scores else None, "conflict_count": sum("conflicting_values" in row["warnings"] for row in group), "incomplete_count": sum("missing_provenance" in row["reasons"] for row in group)})
    return {"report_version": REPORT_VERSION, "quality_policy_version": "quality-confidence-v1", "reference_time": _reference(reference_time), "include_historical": include_historical, "readiness_distribution": distributions, "subjects": by_type}


def business_report(connection: sqlite3.Connection, *, include_historical: bool = False, reference_time: datetime | None = None) -> dict[str, Any]:
    if include_historical:
        source = "business_fact_observations"
    else:
        source = "(SELECT bf.* FROM business_fact_observations bf JOIN (SELECT website_page_id, content_hash, MAX(id) AS snapshot_id FROM business_fact_observations GROUP BY website_page_id, content_hash) s ON s.snapshot_id IN (SELECT MAX(snapshot_id) FROM (SELECT website_page_id, content_hash, MAX(id) snapshot_id FROM business_fact_observations GROUP BY website_page_id, content_hash) latest GROUP BY website_page_id) AND s.website_page_id=bf.website_page_id AND s.content_hash=bf.content_hash)"
    rows = [dict(row) for row in connection.execute(f"SELECT * FROM {source} ORDER BY entity_id, website_id, website_page_id, fact_key, normalized_value, id")]
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((row["entity_id"], row["fact_key"], row["scope"], row["scope_entity_id"]), []).append(row)
    states = {state: 0 for state in ("observed", "repeated", "conflict", "ambiguous_scope")}
    fact_keys: list[dict[str, Any]] = []
    for key, values in sorted(groups.items(), key=lambda item: tuple(str(value) for value in item[0])):
        normalized = sorted({str(value["normalized_value"]) for value in values})
        state = "ambiguous_scope" if key[2] == "ambiguous" else "conflict" if len(normalized) > 1 else "repeated" if len(values) > 1 else "observed"
        states[state] += 1
        fact_keys.append({"entity_id": key[0], "fact_key": key[1], "scope": key[2], "scope_entity_id": key[3], "observation_count": len(values), "values": normalized, "state": state})
    return {"report_version": REPORT_VERSION, "reference_time": _reference(reference_time), "include_historical": include_historical, "observation_count": len(rows), "group_count": len(fact_keys), "state_counts": states, "fact_keys": fact_keys}


def people_report(connection: sqlite3.Connection, *, include_historical: bool = False, reference_time: datetime | None = None) -> dict[str, Any]:
    status_clause = "1=1" if include_historical else "p.status='active'"
    row = connection.execute(f"""
        WITH eligible_people AS (SELECT id FROM people p WHERE {status_clause}),
        contacts AS (SELECT COUNT(DISTINCT CASE WHEN c.contact_type='email' AND c.active=1 THEN c.person_id END) email_count, COUNT(DISTINCT CASE WHEN c.contact_type='phone' AND c.active=1 THEN c.person_id END) phone_count FROM person_contact_points c JOIN eligible_people p ON p.id=c.person_id),
        reviews AS (SELECT SUM(q.status='accepted') accepted, SUM(q.status='rejected') rejected, SUM(q.status='deferred') deferred FROM person_observation_review_queue q JOIN person_evidence e ON e.observation_id=q.observation_id JOIN eligible_people p ON p.id=e.person_id),
        tasks AS (SELECT SUM(t.status IN ('open','in_progress','blocked')) active, SUM(t.status='blocked') blocked, SUM(t.status='stale') stale, SUM(t.status IN ('open','in_progress','blocked') AND t.due_at IS NOT NULL AND t.due_at < ?) overdue FROM person_anomaly_remediation_tasks t JOIN eligible_people p ON p.id=t.person_id)
        SELECT (SELECT COUNT(*) FROM eligible_people) people_count, contacts.*, reviews.*, tasks.* FROM contacts CROSS JOIN reviews CROSS JOIN tasks
    """, (_reference(reference_time),)).fetchone()
    return {"report_version": REPORT_VERSION, "reference_time": _reference(reference_time), "include_historical": include_historical, "people_count": int(row["people_count"]), "contact_counts": {"with_email": int(row["email_count"] or 0), "with_phone": int(row["phone_count"] or 0)}, "review_counts": {key: int(row[key] or 0) for key in ("accepted", "rejected", "deferred")}, "remediation_counts": {key: int(row[key] or 0) for key in ("active", "blocked", "stale", "overdue")}}


def summary_report(connection: sqlite3.Connection, *, include_historical: bool = False, reference_time: datetime | None = None) -> dict[str, Any]:
    return {"report_version": REPORT_VERSION, "reference_time": _reference(reference_time), "include_historical": include_historical, "coverage": coverage_report(connection, include_historical=include_historical, reference_time=reference_time), "quality": quality_report(connection, include_historical=include_historical, reference_time=reference_time), "business": business_report(connection, include_historical=include_historical, reference_time=reference_time), "people": people_report(connection, include_historical=include_historical, reference_time=reference_time)}


def stable_json(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def content_hash(payload: Any) -> str:
    return hashlib.sha256(stable_json(payload)).hexdigest()
