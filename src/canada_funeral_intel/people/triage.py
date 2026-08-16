from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import StrEnum

from canada_funeral_intel.people.audit import audit_people_list, audit_person
from canada_funeral_intel.people.models import PersonResolutionError, PersonStatus


class TriageSeverity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


SEVERITY_BY_CODE: dict[str, TriageSeverity] = {
    "merge_state_inconsistent": TriageSeverity.CRITICAL,
    "rolled_back_merge_not_restored": TriageSeverity.CRITICAL,
    "merge_history_missing_absorbed_person": TriageSeverity.CRITICAL,
    "active_person_zero_evidence": TriageSeverity.HIGH,
    "rejected_only_evidence": TriageSeverity.HIGH,
    "cross_branch_unsupported": TriageSeverity.HIGH,
    "conflicting_active_emails": TriageSeverity.HIGH,
    "conflicting_active_phones": TriageSeverity.MEDIUM,
    "affiliation_incomplete": TriageSeverity.MEDIUM,
    "contact_incomplete": TriageSeverity.MEDIUM,
}

SEVERITY_RANK = {
    TriageSeverity.CRITICAL: 1,
    TriageSeverity.HIGH: 2,
    TriageSeverity.MEDIUM: 3,
    TriageSeverity.LOW: 4,
}

MESSAGE_BY_CODE = {
    "merge_state_inconsistent": "active merge history does not match absorbed person state",
    "rolled_back_merge_not_restored": "rolled-back merge did not restore the absorbed person",
    "merge_history_missing_absorbed_person": "merge history references a missing absorbed person",
    "active_person_zero_evidence": "active person has no canonical evidence association",
    "rejected_only_evidence": "person evidence has no accepted review decision",
    "cross_branch_unsupported": "active affiliations span explicit branches without supporting provenance",
    "conflicting_active_emails": "active contact points contain conflicting email identities",
    "conflicting_active_phones": "active contact points contain conflicting phone identities",
    "affiliation_incomplete": "active affiliation is missing traceable provenance",
    "contact_incomplete": "active contact point is missing traceable provenance",
}


@dataclass(frozen=True, slots=True)
class TriageFilters:
    person_id: int | None = None
    anomaly: str | None = None
    severity: TriageSeverity | None = None
    traceability: str | None = None
    entity_id: int | None = None
    branch_id: int | None = None
    website_id: int | None = None
    page_id: int | None = None
    review_status: str | None = None
    has_email: bool = False
    has_phone: bool = False
    disposition_status: str | None = None
    unreviewed_only: bool = False
    has_remediation: bool = False
    no_remediation: bool = False
    remediation_status: str | None = None
    remediation_owner: str | None = None
    overdue_remediation: bool = False
    include_historical: bool = False
    limit: int | None = None
    reference_time: str | None = None

    def validate(self) -> None:
        for name, value in (
            ("person_id", self.person_id),
            ("entity_id", self.entity_id),
            ("branch_id", self.branch_id),
            ("website_id", self.website_id),
            ("page_id", self.page_id),
        ):
            if value is not None and value < 1:
                raise PersonResolutionError(f"{name} must be positive")
        if self.limit is not None and self.limit < 1:
            raise PersonResolutionError("limit must be positive")
        if self.traceability is not None and self.traceability not in {
            "traceable",
            "incomplete",
            "orphaned",
        }:
            raise PersonResolutionError("invalid traceability status")
        if self.review_status is not None and self.review_status not in {
            "pending",
            "accepted",
            "rejected",
            "deferred",
        }:
            raise PersonResolutionError("invalid review status")
        if self.disposition_status is not None and self.disposition_status not in {
            "open",
            "acknowledged",
            "dismissed",
            "reopened",
            "stale",
        }:
            raise PersonResolutionError("invalid disposition status")
        if self.has_remediation and self.no_remediation:
            raise PersonResolutionError(
                "has_remediation and no_remediation cannot be combined"
            )
        if self.remediation_status is not None and self.remediation_status not in {
            "open",
            "in_progress",
            "blocked",
            "completed",
            "cancelled",
            "stale",
        }:
            raise PersonResolutionError("invalid remediation status")


def _ids(values: list[object]) -> list[int]:
    return sorted({int(value) for value in values if value is not None})


def _supporting_ids(
    audit: dict[str, object], anomaly: dict[str, object]
) -> dict[str, list[int]]:
    observations = list(audit["evidence"]) + list(audit["historical_evidence"])
    if anomaly.get("observation_ids"):
        selected = {int(value) for value in anomaly["observation_ids"]}
        observations = [
            row for row in observations if int(row["observation_id"]) in selected
        ]
    if anomaly.get("affiliation_id") is not None:
        selected = int(anomaly["affiliation_id"])
        observations = [
            row
            for row in observations
            if any(
                int(item["affiliation_id"]) == selected
                and int(item["source_observation_id"]) == int(row["observation_id"])
                for item in audit["affiliations"] + audit["historical_affiliations"]
            )
        ]
    if anomaly.get("contact_id") is not None:
        selected = int(anomaly["contact_id"])
        observations = [
            row
            for row in observations
            if any(
                int(item["contact_id"]) == selected
                and int(item["source_observation_id"]) == int(row["observation_id"])
                for item in audit["contact_points"] + audit["historical_contact_points"]
            )
        ]
    if anomaly.get("merge_id") is not None:
        merge = int(anomaly["merge_id"])
        observations = [
            row
            for row in observations
            if any(
                int(item.get("merge_id", -1)) == merge
                for item in audit["historical_evidence"]
            )
        ]
    contact_ids = [anomaly.get("contact_id")]
    if str(anomaly.get("code", "")).startswith("conflicting_active_"):
        contact_type = (
            "email" if anomaly["code"] == "conflicting_active_emails" else "phone"
        )
        contact_ids.extend(
            row["contact_id"]
            for row in audit["contact_points"]
            if row["active"] == 1 and row["contact_type"] == contact_type
        )
    return {
        "person_ids": _ids([audit["person"]["person_id"]]),
        "observation_ids": _ids([row["observation_id"] for row in observations]),
        "affiliation_ids": _ids([anomaly.get("affiliation_id")]),
        "contact_ids": _ids(contact_ids),
        "merge_ids": _ids([anomaly.get("merge_id")]),
        "entity_ids": _ids([row["entity_id"] for row in observations]),
        "website_ids": _ids([row["website_id"] for row in observations]),
        "page_ids": _ids([row["website_page_id"] for row in observations]),
    }


def _anomaly_matches(
    anomaly: dict[str, object], *, code: str | None, severity: TriageSeverity | None
) -> bool:
    if code is not None and anomaly["code"] != code:
        return False
    return (
        severity is None
        or SEVERITY_BY_CODE.get(str(anomaly["code"]), TriageSeverity.LOW) is severity
    )


def _record_matches(record: dict[str, object], filters: TriageFilters) -> bool:
    audit = record["_audit"]
    if (filters.anomaly is not None or filters.severity is not None) and not any(
        _anomaly_matches(item, code=filters.anomaly, severity=filters.severity)
        for item in audit["anomalies"]
    ):
        return False
    if (
        filters.traceability is not None
        and audit["traceability"]["status"] != filters.traceability
    ):
        return False
    if filters.entity_id is not None and filters.entity_id not in record["entity_ids"]:
        return False
    if filters.branch_id is not None and filters.branch_id not in record["branch_ids"]:
        return False
    if (
        filters.website_id is not None
        and filters.website_id not in record["website_ids"]
    ):
        return False
    if filters.page_id is not None and filters.page_id not in record["page_ids"]:
        return False
    if (
        filters.review_status is not None
        and filters.review_status not in record["review_statuses"]
    ):
        return False
    if filters.has_email and not record["emails"]:
        return False
    if filters.has_phone and not record["phones"]:
        return False
    if filters.disposition_status is not None or filters.unreviewed_only:
        anomaly_dispositions = [item.get("disposition") for item in record["anomalies"]]
        if filters.unreviewed_only and not any(
            item is None for item in anomaly_dispositions
        ):
            return False
        if filters.disposition_status is not None and not any(
            item is not None and item["status"] == filters.disposition_status
            for item in anomaly_dispositions
        ):
            return False
    remediation = [item.get("remediation") for item in record["anomalies"]]
    if filters.has_remediation and not any(
        item is not None and item["remediation_task_count"] for item in remediation
    ):
        return False
    if filters.no_remediation and any(
        item is not None and item["remediation_task_count"] for item in remediation
    ):
        return False
    if filters.remediation_status is not None and not any(
        item is not None and filters.remediation_status in item["remediation_statuses"]
        for item in remediation
    ):
        return False
    if filters.remediation_owner is not None:
        owners = {
            str(owner)
            for item in remediation
            if item is not None
            for owner in item.get("remediation_owners", [])
        }
        if filters.remediation_owner not in owners:
            return False
    return not (
        filters.overdue_remediation
        and not any(
            item is not None and item["overdue_remediation_task_count"]
            for item in remediation
        )
    )


def _build_record(
    connection: sqlite3.Connection, audit: dict[str, object]
) -> dict[str, object]:
    person = audit["person"]
    current_affiliations = [row for row in audit["affiliations"] if row["active"] == 1]
    current_contacts = [row for row in audit["contact_points"] if row["active"] == 1]
    observations = list(audit["evidence"])
    observation_rows = observations + list(audit["historical_evidence"])
    review_statuses = sorted({str(row["status"]) for row in audit["reviews"]})
    source_observation_ids = {
        int(row["source_observation_id"])
        for row in current_affiliations + current_contacts
    }
    if source_observation_ids:
        marks = ",".join("?" for _ in source_observation_ids)
        provenance = connection.execute(
            f"SELECT id AS observation_id, website_id, website_page_id AS page_id, entity_id FROM website_page_person_observations WHERE id IN ({marks}) ORDER BY id",
            tuple(sorted(source_observation_ids)),
        ).fetchall()
        observation_rows.extend(
            dict(row)
            for row in provenance
            if int(row["observation_id"])
            not in {int(item["observation_id"]) for item in observation_rows}
        )
    entity_ids = _ids(
        [row["entity_id"] for row in observation_rows]
        + [row["entity_id"] for row in current_affiliations]
    )
    branch_ids = _ids(
        [
            row["entity_id"]
            for row in current_affiliations
            if row.get("entity_type") == "branch"
        ]
    )
    website_ids = _ids([row["website_id"] for row in observation_rows])
    page_ids = _ids(
        [row.get("website_page_id", row.get("page_id")) for row in observation_rows]
    )
    anomalies = []
    for raw in audit["anomalies"]:
        code = str(raw["code"])
        severity = SEVERITY_BY_CODE.get(code, TriageSeverity.LOW)
        anomalies.append(
            {
                "code": code,
                "severity": severity.value,
                "message": MESSAGE_BY_CODE.get(code, "unclassified audit anomaly"),
                "supporting_ids": _supporting_ids(audit, raw),
                "values": sorted({str(value) for value in raw.get("values", [])}),
            }
        )
    anomalies.sort(
        key=lambda row: (
            SEVERITY_RANK[TriageSeverity(row["severity"])],
            row["code"],
            tuple(
                row["supporting_ids"]["merge_ids"]
                + row["supporting_ids"]["affiliation_ids"]
                + row["supporting_ids"]["contact_ids"]
            ),
        )
    )
    highest = (
        TriageSeverity.LOW
        if not anomalies
        else TriageSeverity(
            min(
                anomalies,
                key=lambda row: SEVERITY_RANK[TriageSeverity(row["severity"])],
            )["severity"]
        )
    )
    return {
        "_audit": audit,
        "person_id": int(person["person_id"]),
        "person_status": str(person["status"]),
        "display_name": str(person["canonical_name"]),
        "triage_priority": SEVERITY_RANK[highest],
        "severity": highest.value,
        "anomaly_count": len(anomalies),
        "anomaly_codes": [row["code"] for row in anomalies],
        "anomalies": anomalies,
        "traceability_status": str(audit["traceability"]["status"]),
        "observation_count": len(
            {int(row["observation_id"]) for row in observation_rows}
        ),
        "accepted_review_count": sum(
            1 for row in audit["reviews"] if row["status"] == "accepted"
        ),
        "rejected_review_count": sum(
            1 for row in audit["reviews"] if row["status"] == "rejected"
        ),
        "deferred_review_count": sum(
            1 for row in audit["reviews"] if row["status"] == "deferred"
        ),
        "pending_review_count": sum(
            1 for row in audit["reviews"] if row["status"] == "pending"
        ),
        "active_affiliation_count": len(current_affiliations),
        "total_affiliation_count": len(audit["affiliations"]),
        "active_contact_count": len(current_contacts),
        "total_contact_count": len(audit["contact_points"]),
        "merge_count": len(audit["merge_history"]),
        "rollback_count": sum(
            1 for row in audit["merge_history"] if row["state"] == "rolled_back"
        ),
        "entity_ids": entity_ids,
        "branch_ids": branch_ids,
        "website_ids": website_ids,
        "page_ids": page_ids,
        "review_statuses": review_statuses,
        "emails": sorted(
            {
                str(row["normalized_value"])
                for row in current_contacts
                if row["contact_type"] == "email" and row["normalized_value"]
            }
        ),
        "phones": sorted(
            {
                str(row["normalized_value"])
                for row in current_contacts
                if row["contact_type"] == "phone" and row["normalized_value"]
            }
        ),
    }


def triage_people(
    connection: sqlite3.Connection, filters: TriageFilters | None = None
) -> list[dict[str, object]]:
    filters = filters or TriageFilters()
    filters.validate()
    if filters.person_id is not None:
        person_ids = [filters.person_id]
    else:
        summaries = audit_people_list(
            connection, include_historical=filters.include_historical
        )
        person_ids = [int(row["person_id"]) for row in summaries]
    records: list[dict[str, object]] = []
    from canada_funeral_intel.people.dispositions import (
        dispositions_for_fingerprints,
        fingerprint_anomaly,
    )
    from canada_funeral_intel.people.remediation import summaries_for_fingerprints

    for person_id in person_ids:
        audit = audit_person(connection, person_id, include_remediation=False)
        if (
            not filters.include_historical
            and audit["person"]["status"] != PersonStatus.ACTIVE.value
        ):
            continue
        record = _build_record(connection, audit)
        records.append(record)
    disposition_keys = []
    for record in records:
        for anomaly in record["anomalies"]:
            disposition_keys.append(
                (
                    int(record["person_id"]),
                    str(anomaly["code"]),
                    fingerprint_anomaly(int(record["person_id"]), anomaly),
                )
            )
    dispositions = dispositions_for_fingerprints(connection, disposition_keys)
    remediations = summaries_for_fingerprints(
        connection, disposition_keys, now=filters.reference_time
    )
    for record in records:
        for anomaly in record["anomalies"]:
            fingerprint = fingerprint_anomaly(int(record["person_id"]), anomaly)
            anomaly["fingerprint"] = fingerprint
            disposition = dispositions.get(
                (int(record["person_id"]), str(anomaly["code"]), fingerprint)
            )
            anomaly["disposition"] = disposition
            anomaly["remediation"] = remediations.get(
                (int(record["person_id"]), str(anomaly["code"]), fingerprint)
            )
    records = [record for record in records if _record_matches(record, filters)]
    for record in records:
        record.pop("_audit")
    records.sort(
        key=lambda row: (
            int(row["triage_priority"]),
            -int(row["anomaly_count"]),
            int(row["person_id"]),
        )
    )
    if filters.limit is not None:
        records = records[: filters.limit]
    return records
