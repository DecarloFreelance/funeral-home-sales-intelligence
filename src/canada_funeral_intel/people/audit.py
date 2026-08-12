from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from canada_funeral_intel.people.models import PersonResolutionError, PersonStatus


def _row_dict(row: sqlite3.Row | None) -> dict[str, object] | None:
    return None if row is None else dict(row)


def _traceability(observation: dict[str, object] | None) -> tuple[str, list[str]]:
    if observation is None:
        return "orphaned", ["missing_observation"]
    reasons: list[str] = []
    if observation.get("page_id") is None:
        reasons.append("missing_page")
    if observation.get("website_id") is None:
        reasons.append("missing_website")
    if observation.get("entity_id") is None:
        reasons.append("missing_entity")
    if observation.get("review_status") is None:
        reasons.append("missing_review_provenance")
    return ("traceable" if not reasons else "incomplete"), reasons


def _observation_details(connection: sqlite3.Connection, observation_ids: set[int]) -> dict[int, dict[str, object]]:
    if not observation_ids:
        return {}
    marks = ",".join("?" for _ in observation_ids)
    rows = connection.execute(
        f"""
        SELECT
            o.id AS observation_id, o.website_page_id AS page_id,
            o.website_id, o.entity_id, o.observed_name, o.normalized_name,
            o.role_title, o.normalized_role, o.email, o.normalized_email,
            o.phone, o.normalized_phone, o.branch_context, o.confidence,
            o.extraction_method, o.extractor_version, o.evidence_snippet,
            o.source_url, o.content_hash, o.created_at, o.updated_at,
            p.url AS page_url, p.normalized_url AS page_normalized_url,
            p.page_kind, p.identity_score, p.identity_observable,
            p.status_code, p.content_type, p.depth,
            w.website_kind, w.confidence AS website_confidence,
            w.status AS website_status, w.is_primary,
            w.discovery_method, e.entity_type, e.canonical_name AS entity_name,
            e.parent_entity_id, e.status AS entity_status,
            q.id AS review_queue_id, q.status AS review_status,
            q.reviewer_note, q.reviewed_at
        FROM website_page_person_observations AS o
        LEFT JOIN website_pages AS p ON p.id = o.website_page_id
        LEFT JOIN websites AS w ON w.id = o.website_id
        LEFT JOIN entities AS e ON e.id = o.entity_id
        LEFT JOIN person_observation_review_queue AS q ON q.observation_id = o.id
        WHERE o.id IN ({marks})
        ORDER BY o.id
        """,
        tuple(sorted(observation_ids)),
    ).fetchall()
    return {int(row["observation_id"]): dict(row) for row in rows}


def _observation_payload(row: dict[str, object], *, association_id: int | None = None, historical: bool = False) -> dict[str, object]:
    status, reasons = _traceability(row)
    return {
        "association_id": association_id,
        "historical": historical,
        "traceability": status,
        "traceability_reasons": reasons,
        "observation_id": row["observation_id"],
        "website_page_id": row["page_id"],
        "website_id": row["website_id"],
        "entity_id": row["entity_id"],
        "observed_name": row["observed_name"],
        "normalized_name": row["normalized_name"],
        "role_title": row["role_title"],
        "normalized_role": row["normalized_role"],
        "email": row["email"],
        "normalized_email": row["normalized_email"],
        "phone": row["phone"],
        "normalized_phone": row["normalized_phone"],
        "branch_context": row["branch_context"],
        "confidence": row["confidence"],
        "extraction_method": row["extraction_method"],
        "extractor_version": row["extractor_version"],
        "evidence_snippet": row["evidence_snippet"],
        "source_url": row["source_url"],
        "content_hash": row["content_hash"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "page": {
            "url": row["page_url"],
            "normalized_url": row["page_normalized_url"],
            "page_kind": row["page_kind"],
            "identity_score": row["identity_score"],
            "identity_observable": row["identity_observable"],
            "status_code": row["status_code"],
            "content_type": row["content_type"],
            "depth": row["depth"],
        },
        "website": {
            "website_id": row["website_id"],
            "website_kind": row["website_kind"],
            "confidence": row["website_confidence"],
            "status": row["website_status"],
            "is_primary": row["is_primary"],
            "discovery_method": row["discovery_method"],
        },
        "entity": {
            "entity_id": row["entity_id"],
            "entity_type": row["entity_type"],
            "canonical_name": row["entity_name"],
            "parent_entity_id": row["parent_entity_id"],
            "status": row["entity_status"],
        },
    }


def _review_rows(connection: sqlite3.Connection, observation_ids: set[int]) -> list[dict[str, object]]:
    if not observation_ids:
        return []
    marks = ",".join("?" for _ in observation_ids)
    rows = connection.execute(
        f"SELECT id AS review_queue_id, observation_id, status, reviewer_note, created_at, reviewed_at FROM person_observation_review_queue WHERE observation_id IN ({marks}) ORDER BY observation_id, id",
        tuple(sorted(observation_ids)),
    ).fetchall()
    return [dict(row) for row in rows]


def _merge_rows(connection: sqlite3.Connection, person_id: int) -> list[dict[str, object]]:
    rows = connection.execute(
        """
        SELECT id AS merge_id, survivor_person_id, merged_person_id AS absorbed_person_id,
               reason AS merge_reason, decision_source AS actor, created_at,
               rolled_back_at, rollback_actor, rollback_reason,
               CASE WHEN rolled_back_at IS NULL THEN 'active' ELSE 'rolled_back' END AS state
        FROM person_merge_history
        WHERE survivor_person_id = ? OR merged_person_id = ?
        ORDER BY id
        """,
        (person_id, person_id),
    ).fetchall()
    return [dict(row) for row in rows]


def _anomalies(
    connection: sqlite3.Connection,
    *,
    person: dict[str, object],
    affiliations: list[dict[str, object]],
    contacts: list[dict[str, object]],
    evidence: list[dict[str, object]],
    reviews: list[dict[str, object]],
    merges: list[dict[str, object]],
) -> list[dict[str, object]]:
    anomalies: list[dict[str, object]] = []

    def add(code: str, **details: object) -> None:
        anomalies.append({"code": code, **details})

    accepted = [row for row in reviews if row["status"] == "accepted"]
    if person["status"] == PersonStatus.ACTIVE.value and not evidence:
        add("active_person_zero_evidence", person_id=person["person_id"])
    if evidence and not accepted:
        add("rejected_only_evidence", person_id=person["person_id"], observation_ids=sorted({int(row["observation_id"]) for row in evidence}))

    for row in affiliations:
        if row["active"] != 1 or row["traceability"] == "traceable":
            continue
        add("affiliation_incomplete", affiliation_id=row["affiliation_id"], reasons=row["traceability_reasons"])
    for row in contacts:
        if row["active"] != 1 or row["traceability"] == "traceable":
            continue
        add("contact_incomplete", contact_id=row["contact_id"], reasons=row["traceability_reasons"])

    for contact_type, code in (("email", "conflicting_active_emails"), ("phone", "conflicting_active_phones")):
        values = sorted({str(row["normalized_value"]) for row in contacts if row["active"] == 1 and row["contact_type"] == contact_type})
        if len(values) > 1:
            add(code, values=values)

    branch_ids = sorted({int(row["entity_id"]) for row in affiliations if row["active"] == 1 and row.get("entity_type") == "branch"})
    if len(branch_ids) > 1:
        add("cross_branch_unsupported", entity_ids=branch_ids)

    for merge in merges:
        absorbed = connection.execute("SELECT status FROM people WHERE id = ?", (merge["absorbed_person_id"],)).fetchone()
        if absorbed is None:
            add("merge_history_missing_absorbed_person", merge_id=merge["merge_id"])
        elif merge["state"] == "active" and absorbed["status"] != PersonStatus.MERGED.value:
            add("merge_state_inconsistent", merge_id=merge["merge_id"])
        elif merge["state"] == "rolled_back" and absorbed["status"] != PersonStatus.ACTIVE.value:
            add("rolled_back_merge_not_restored", merge_id=merge["merge_id"])

    anomalies.sort(key=lambda row: (str(row["code"]), str(row.get("merge_id", row.get("observation_ids", row.get("affiliation_id", row.get("contact_id", "")))))))
    return anomalies


def audit_person(connection: sqlite3.Connection, person_id: int) -> dict[str, object]:
    if person_id < 1:
        raise PersonResolutionError("person_id must be positive")
    try:
        person_row = connection.execute("SELECT id AS person_id, canonical_name, normalized_name, status, created_at, updated_at FROM people WHERE id = ?", (person_id,)).fetchone()
        if person_row is None:
            raise PersonResolutionError(f"Person not found: {person_id}")
        person = dict(person_row)
        affiliation_rows = connection.execute(
            """
            SELECT a.id AS affiliation_id, a.entity_id, a.observed_role, a.normalized_role,
                   a.branch_context, a.confidence, a.source_observation_id, a.active,
                   e.entity_type
            FROM person_affiliations AS a LEFT JOIN entities AS e ON e.id = a.entity_id
            WHERE a.person_id = ? ORDER BY a.active DESC, a.entity_id, a.id
            """,
            (person_id,),
        ).fetchall()
        contact_rows = connection.execute(
            "SELECT id AS contact_id, contact_type, observed_value, normalized_value, confidence, source_observation_id, active FROM person_contact_points WHERE person_id = ? ORDER BY active DESC, contact_type, normalized_value, id",
            (person_id,),
        ).fetchall()
        evidence_rows = connection.execute(
            "SELECT id AS evidence_id, observation_id, resolution_candidate_id, review_decision FROM person_evidence WHERE person_id = ? ORDER BY observation_id, id",
            (person_id,),
        ).fetchall()
        merges = _merge_rows(connection, person_id)
        observation_ids = {int(row["source_observation_id"]) for row in affiliation_rows}
        observation_ids.update(int(row["source_observation_id"]) for row in contact_rows)
        observation_ids.update(int(row["observation_id"]) for row in evidence_rows)
        historical_affiliation_rows = connection.execute(
            """
            SELECT h.merge_history_id AS merge_id, h.affiliation_id,
                   h.entity_id, h.observed_role, h.normalized_role,
                   h.branch_context, h.confidence, h.source_observation_id,
                   h.previous_active
            FROM person_merge_affiliation_history AS h
            JOIN person_merge_history AS m ON m.id = h.merge_history_id
            WHERE m.survivor_person_id = ? AND h.action = 'deduplicated'
            ORDER BY h.merge_history_id, h.affiliation_id
            """,
            (person_id,),
        ).fetchall()
        historical_contact_rows = connection.execute(
            """
            SELECT h.merge_history_id AS merge_id, h.contact_id,
                   h.contact_type, h.observed_value, h.normalized_value,
                   h.confidence, h.source_observation_id, h.previous_active
            FROM person_merge_contact_history AS h
            JOIN person_merge_history AS m ON m.id = h.merge_history_id
            WHERE m.survivor_person_id = ? AND h.action = 'deduplicated'
            ORDER BY h.merge_history_id, h.contact_id
            """,
            (person_id,),
        ).fetchall()
        historical_evidence_rows = connection.execute(
            """
            SELECT h.merge_history_id AS merge_id, h.evidence_id,
                   h.observation_id, h.resolution_candidate_id,
                   h.review_decision
            FROM person_merge_evidence_history AS h
            JOIN person_merge_history AS m ON m.id = h.merge_history_id
            WHERE m.survivor_person_id = ? AND h.action = 'deduplicated'
            ORDER BY h.merge_history_id, h.evidence_id
            """,
            (person_id,),
        ).fetchall()
        observation_ids.update(int(row["source_observation_id"]) for row in historical_affiliation_rows)
        observation_ids.update(int(row["source_observation_id"]) for row in historical_contact_rows)
        observation_ids.update(int(row["observation_id"]) for row in historical_evidence_rows)
        details = _observation_details(connection, observation_ids)
        reviews = _review_rows(connection, observation_ids)

        affiliations = []
        for row in affiliation_rows:
            value = dict(row)
            observation = details.get(int(row["source_observation_id"]))
            status, reasons = _traceability(observation)
            value.update({"traceability": status, "traceability_reasons": reasons, "entity_type": row["entity_type"]})
            affiliations.append(value)
        contacts = []
        for row in contact_rows:
            value = dict(row)
            status, reasons = _traceability(details.get(int(row["source_observation_id"])))
            value.update({"traceability": status, "traceability_reasons": reasons})
            contacts.append(value)
        historical_affiliations = []
        for row in historical_affiliation_rows:
            status, reasons = _traceability(details.get(int(row["source_observation_id"])))
            historical_affiliations.append({"person_id": person_id, "historical": True, "traceability": status, "traceability_reasons": reasons, **dict(row)})
        historical_contacts = []
        for row in historical_contact_rows:
            status, reasons = _traceability(details.get(int(row["source_observation_id"])))
            historical_contacts.append({"person_id": person_id, "historical": True, "traceability": status, "traceability_reasons": reasons, **dict(row)})
        evidence = [_observation_payload(details[int(row["observation_id"])], association_id=int(row["evidence_id"])) for row in evidence_rows if int(row["observation_id"]) in details]
        historical_evidence = [_observation_payload(details[int(row["observation_id"])], association_id=int(row["evidence_id"]), historical=True) for row in historical_evidence_rows if int(row["observation_id"]) in details]
        anomalies = _anomalies(connection, person=person, affiliations=affiliations, contacts=contacts, evidence=evidence, reviews=reviews, merges=merges)
        traceability_values = [str(row["traceability"]) for row in affiliations + contacts + evidence + historical_affiliations + historical_contacts + historical_evidence]
        traceability = "traceable" if traceability_values and all(value == "traceable" for value in traceability_values) else ("incomplete" if traceability_values else "orphaned")
        return {
            "person": person,
            "affiliations": affiliations,
            "historical_affiliations": historical_affiliations,
            "contact_points": contacts,
            "historical_contact_points": historical_contacts,
            "evidence": evidence,
            "historical_evidence": historical_evidence,
            "reviews": reviews,
            "merge_history": merges,
            "traceability": {"status": traceability, "observation_count": len(observation_ids), "anomaly_count": len(anomalies)},
            "anomalies": anomalies,
        }
    except sqlite3.Error as exc:
        raise PersonResolutionError(f"person audit failed: {exc}") from exc


def audit_people_list(connection: sqlite3.Connection, *, include_historical: bool = False) -> list[dict[str, object]]:
    status_clause = "" if include_historical else "WHERE p.status = 'active'"
    try:
        rows = connection.execute(
            f"""
            WITH person_observations AS (
                SELECT person_id, observation_id FROM person_evidence
                UNION SELECT person_id, source_observation_id FROM person_affiliations
                UNION SELECT person_id, source_observation_id FROM person_contact_points
            ),
            observation_summary AS (
                SELECT po.person_id, COUNT(DISTINCT po.observation_id) AS observation_count,
                       COUNT(DISTINCT q.id) AS review_count,
                       SUM(CASE WHEN q.id IS NULL THEN 1 ELSE 0 END) AS missing_review_count,
                       SUM(CASE WHEN q.status = 'accepted' THEN 1 ELSE 0 END) AS accepted_review_count
                FROM person_observations AS po
                LEFT JOIN person_observation_review_queue AS q ON q.observation_id = po.observation_id
                GROUP BY po.person_id
            ),
            evidence_summary AS (
                SELECT person_id, COUNT(*) AS evidence_count FROM person_evidence GROUP BY person_id
            ),
            affiliation_summary AS (
                SELECT person_id, COUNT(*) AS affiliation_count FROM person_affiliations WHERE active = 1 GROUP BY person_id
            ),
            contact_summary AS (
                SELECT person_id, COUNT(*) AS contact_count FROM person_contact_points WHERE active = 1 GROUP BY person_id
            ),
            merge_summary AS (
                SELECT person_id, COUNT(*) AS merge_count FROM (
                    SELECT survivor_person_id AS person_id FROM person_merge_history
                    UNION ALL SELECT merged_person_id AS person_id FROM person_merge_history
                ) GROUP BY person_id
            )
            SELECT p.id AS person_id, p.canonical_name, p.status,
                   COALESCE(a.affiliation_count, 0) AS affiliation_count,
                   COALESCE(c.contact_count, 0) AS contact_count,
                   COALESCE(o.observation_count, 0) AS observation_count,
                   COALESCE(o.review_count, 0) AS review_count,
                   COALESCE(m.merge_count, 0) AS merge_count,
                   CASE WHEN COALESCE(o.observation_count, 0) = 0 THEN 'orphaned'
                        WHEN COALESCE(o.missing_review_count, 0) > 0 THEN 'incomplete'
                        ELSE 'traceable' END AS traceability_status,
                   (
                       CASE WHEN p.status = 'active' AND COALESCE(e.evidence_count, 0) = 0 THEN 1 ELSE 0 END
                       + CASE WHEN COALESCE(e.evidence_count, 0) > 0 AND COALESCE(o.accepted_review_count, 0) = 0 THEN 1 ELSE 0 END
                       + CASE WHEN EXISTS (
                           SELECT 1 FROM person_contact_points AS c1
                           JOIN person_contact_points AS c2 ON c2.person_id = c1.person_id
                           WHERE c1.person_id = p.id AND c1.active = 1 AND c2.active = 1
                             AND c1.contact_type = c2.contact_type
                             AND c1.normalized_value <> c2.normalized_value
                       ) THEN 1 ELSE 0 END
                       + CASE WHEN (SELECT COUNT(DISTINCT a2.entity_id)
                                    FROM person_affiliations AS a2
                                    JOIN entities AS e2 ON e2.id = a2.entity_id
                                    WHERE a2.person_id = p.id AND a2.active = 1 AND e2.entity_type = 'branch') > 1
                              THEN 1 ELSE 0 END
                   ) AS anomaly_count
            FROM people AS p
            LEFT JOIN observation_summary AS o ON o.person_id = p.id
            LEFT JOIN evidence_summary AS e ON e.person_id = p.id
            LEFT JOIN affiliation_summary AS a ON a.person_id = p.id
            LEFT JOIN contact_summary AS c ON c.person_id = p.id
            LEFT JOIN merge_summary AS m ON m.person_id = p.id
            {status_clause}
            ORDER BY p.normalized_name, p.id
            """
        ).fetchall()
        return [{"person_id": int(row["person_id"]), "status": str(row["status"]), "canonical_name": str(row["canonical_name"]), "affiliation_count": int(row["affiliation_count"]), "contact_count": int(row["contact_count"]), "observation_count": int(row["observation_count"]), "review_count": int(row["review_count"]), "merge_count": int(row["merge_count"]), "traceability_status": str(row["traceability_status"]), "anomaly_count": int(row["anomaly_count"])} for row in rows]
    except sqlite3.Error as exc:
        raise PersonResolutionError(f"people audit listing failed: {exc}") from exc


_EXPORTS: dict[str, tuple[str, ...]] = {
    "people": ("person_id", "canonical_name", "normalized_name", "status", "created_at", "updated_at"),
    "person_affiliations": ("person_id", "affiliation_id", "entity_id", "observed_role", "normalized_role", "branch_context", "confidence", "source_observation_id", "active", "historical", "traceability"),
    "person_contacts": ("person_id", "contact_id", "contact_type", "observed_value", "normalized_value", "confidence", "source_observation_id", "active", "historical", "traceability"),
    "person_observations": ("person_id", "association_id", "historical", "observation_id", "website_page_id", "website_id", "entity_id", "observed_name", "normalized_name", "role_title", "normalized_role", "email", "normalized_email", "phone", "normalized_phone", "branch_context", "confidence", "extraction_method", "extractor_version", "evidence_snippet", "source_url", "content_hash", "review_status", "page_url", "page_kind", "identity_score", "identity_observable", "status_code", "content_type", "depth", "website_kind", "website_status", "is_primary", "entity_type", "entity_name"),
    "person_reviews": ("person_id", "review_queue_id", "observation_id", "status", "reviewer_note", "created_at", "reviewed_at"),
    "person_merge_history": ("person_id", "merge_id", "survivor_person_id", "absorbed_person_id", "merge_reason", "actor", "created_at", "state", "rolled_back_at", "rollback_actor", "rollback_reason"),
    "person_anomalies": ("person_id", "code", "affiliation_id", "contact_id", "merge_id", "observation_ids", "reasons", "values", "entity_ids"),
    "person_triage": ("person_id", "person_status", "display_name", "triage_priority", "severity", "anomaly_count", "anomaly_codes", "anomaly_fingerprints", "disposition_statuses", "disposition_ids", "disposition_actors", "disposition_updated_at", "traceability_status", "entity_ids", "branch_ids", "website_ids", "page_ids", "observation_count", "active_affiliation_count", "active_contact_count", "merge_count", "rollback_count"),
    "person_anomaly_dispositions": ("disposition_id", "person_id", "anomaly_code", "anomaly_fingerprint", "status", "reviewer_actor", "reviewer_note", "created_at", "updated_at", "acknowledged_at", "dismissed_at", "reopened_at", "stale_at"),
    "person_anomaly_disposition_history": ("id", "disposition_id", "person_id", "anomaly_code", "anomaly_fingerprint", "previous_status", "new_status", "actor", "note", "changed_at"),
}


def export_people_csv(connection: sqlite3.Connection, output: Path, *, include_historical: bool = False) -> list[Path]:
    if output.exists() and not output.is_dir():
        raise PersonResolutionError("CSV export output must be a directory")
    output.mkdir(parents=True, exist_ok=True)
    audits = [audit_person(connection, int(row["person_id"])) for row in connection.execute("SELECT id AS person_id FROM people " + ("" if include_historical else "WHERE status = 'active'") + " ORDER BY normalized_name, id").fetchall()]
    rows: dict[str, list[dict[str, object]]] = {name: [] for name in _EXPORTS}
    from canada_funeral_intel.people.triage import TriageFilters, triage_people

    triage_rows = triage_people(connection, TriageFilters(include_historical=include_historical))
    person_ids = [int(audit["person"]["person_id"]) for audit in audits]
    if person_ids:
        marks = ",".join("?" for _ in person_ids)
        disposition_rows = connection.execute(f"SELECT * FROM person_anomaly_dispositions WHERE person_id IN ({marks}) ORDER BY person_id, anomaly_code, id", tuple(person_ids)).fetchall()
        history_rows = connection.execute(f"SELECT * FROM person_anomaly_disposition_history WHERE person_id IN ({marks}) ORDER BY person_id, disposition_id, id", tuple(person_ids)).fetchall()
        rows["person_anomaly_dispositions"].extend(dict(row) for row in disposition_rows)
        rows["person_anomaly_disposition_history"].extend(dict(row) for row in history_rows)
    for audit in audits:
        person_id = int(audit["person"]["person_id"])
        rows["people"].append(audit["person"])
        for item in audit["affiliations"]:
            rows["person_affiliations"].append({"person_id": person_id, **item})
        for item in audit["historical_affiliations"]:
            rows["person_affiliations"].append({"person_id": person_id, **item})
        for item in audit["contact_points"]:
            rows["person_contacts"].append({"person_id": person_id, **item})
        for item in audit["historical_contact_points"]:
            rows["person_contacts"].append({"person_id": person_id, **item})
        for item in audit["evidence"]:
            rows["person_observations"].append({"person_id": person_id, **item, "review_status": next((r["status"] for r in audit["reviews"] if r["observation_id"] == item["observation_id"]), None), **item["page"], **item["website"], **item["entity"]})
        for item in audit["historical_evidence"]:
            rows["person_observations"].append({"person_id": person_id, **item, "review_status": next((r["status"] for r in audit["reviews"] if r["observation_id"] == item["observation_id"]), None), **item["page"], **item["website"], **item["entity"]})
        for item in audit["reviews"]:
            rows["person_reviews"].append({"person_id": person_id, **item})
        for item in audit["merge_history"]:
            rows["person_merge_history"].append({"person_id": person_id, **item})
        for item in audit["anomalies"]:
            rows["person_anomalies"].append({"person_id": person_id, **item})
    for item in triage_rows:
        dispositions = [row["disposition"] for row in item["anomalies"] if row.get("disposition") is not None]
        rows["person_triage"].append({
            **item,
            "anomaly_codes": "|".join(str(code) for code in item["anomaly_codes"]),
            "anomaly_fingerprints": "|".join(sorted(str(row["fingerprint"]) for row in item["anomalies"])),
            "disposition_statuses": "|".join(sorted(str(row["status"]) for row in dispositions)),
            "disposition_ids": "|".join(sorted(str(row["disposition_id"]) for row in dispositions)),
            "disposition_actors": "|".join(sorted(str(row["reviewer_actor"]) for row in dispositions)),
            "disposition_updated_at": "|".join(sorted(str(row["updated_at"]) for row in dispositions)),
            "entity_ids": "|".join(str(value) for value in item["entity_ids"]),
            "branch_ids": "|".join(str(value) for value in item["branch_ids"]),
            "website_ids": "|".join(str(value) for value in item["website_ids"]),
            "page_ids": "|".join(str(value) for value in item["page_ids"]),
        })
    paths: list[Path] = []
    for name, columns in _EXPORTS.items():
        path = output / f"{name}.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
            writer.writeheader()
            for row in sorted(rows[name], key=lambda item: tuple(str(item.get(column) or "") for column in columns)):
                writer.writerow({column: row.get(column) for column in columns})
        paths.append(path)
    return paths
