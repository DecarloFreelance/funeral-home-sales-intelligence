from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from difflib import SequenceMatcher
import re
from typing import Any, Dict, Iterable, List
from urllib.parse import urlsplit

from enrichment.evidence import CONFIDENCE_STATES, utc_now, iso


AGENT = "quality_control"
VERSION = "1.5.0"
CRM_BLOCKING_CODES = {
    "CONFLICTING_FACTS",
    "POSSIBLE_DUPLICATE_ORGANIZATION",
    "ORGANIZATION_WEBSITE_MISMATCH",
    "MULTI_LOCATION_ACCOUNT_REVIEW",
}


def _finding(entity_id: str, code: str, severity: str, message: str, evidence: Any, action: str) -> Dict[str, Any]:
    material = json.dumps([entity_id, code, evidence], sort_keys=True, ensure_ascii=False, default=str)
    return {
        "id": hashlib.sha256(material.encode("utf-8")).hexdigest()[:24],
        "code": code,
        "severity": severity,
        "message": message,
        "evidence": evidence,
        "recommended_action": action,
        "requires_review": severity in {"HIGH", "MEDIUM"},
    }


def _email_domain(email: str) -> str:
    return email.rpartition("@")[2].lower().rstrip(".")


def _normalized_name(value: Any) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))


def readiness_from_findings(findings: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    findings = list(findings)
    crm_blockers = [
        item for item in findings
        if item.get("severity") == "HIGH" or item.get("code") in CRM_BLOCKING_CODES
    ]
    outreach_blockers = [item for item in findings if item.get("requires_review")]
    return {
        "crm_sync_safe": not crm_blockers,
        "outreach_ready": not outreach_blockers,
        "crm_blocking_reasons": [item["code"] for item in crm_blockers],
        "outreach_blocking_reasons": [item["code"] for item in outreach_blockers],
    }


def approved_for_commercial_use(record: Dict[str, Any], *, outreach=False) -> bool:
    """Require explicit current quality approval; absent state fails closed."""
    quality = record.get("quality_control") or {}
    if quality.get("crm_sync_safe") is not True:
        return False
    return quality.get("outreach_ready") is True if outreach else True


def evaluate_quality(record: Dict[str, Any], *, evaluated_at=None) -> Dict[str, Any]:
    """Report ambiguity and invariant violations; never mutate canonical data."""
    evaluated_at = evaluated_at or utc_now()
    entity_id = str(record.get("domain") or record.get("entity_id") or "")
    enrichment = record.get("enrichment") or {}
    facts = enrichment.get("facts") or []
    findings: List[Dict[str, Any]] = []
    if record.get("pages") == 0 or record.get("processing_status") == "NO_USABLE_WEBSITE_EVIDENCE":
        findings.append(_finding(entity_id, "NO_USABLE_WEBSITE_EVIDENCE", "HIGH",
            "No public website page was retrieved for this organization.",
            {"pages": record.get("pages", 0)},
            "Resolve or recrawl the website before CRM synchronization or outreach."))
    locations = (record.get("business_profile") or {}).get("locations") or []
    location_names = sorted({
        " ".join(str(location.get("company") or "").split())
        for location in locations if isinstance(location, dict) and location.get("company")
    })
    if len(location_names) > 1:
        findings.append(_finding(entity_id, "MULTI_LOCATION_ACCOUNT_REVIEW", "MEDIUM",
            "One website domain represents multiple named locations.",
            {"location_count": len(locations), "business_names": location_names[:25]},
            "Choose network-level versus branch-level CRM identity before synchronization."))

    mandatory = {
        "id", "field", "value", "source", "source_url", "source_type",
        "observed_at", "stale_after", "detector", "detector_version",
        "confidence", "verification_state", "evidence", "derived",
    }
    for item in facts:
        missing = sorted(mandatory.difference(item))
        if missing:
            findings.append(_finding(entity_id, "MISSING_PROVENANCE", "HIGH",
                "An enrichment fact is missing mandatory provenance.",
                {"fact_id": item.get("id"), "missing": missing},
                "Regenerate the fact with the provenance-aware extractor."))
        if item.get("verification_state") not in CONFIDENCE_STATES:
            findings.append(_finding(entity_id, "INVALID_CONFIDENCE_STATE", "HIGH",
                "An enrichment fact has an unsupported verification state.",
                {"fact_id": item.get("id"), "state": item.get("verification_state")},
                "Quarantine the fact and rerun its detector."))
        if item.get("verification_state") == "INFERRED" and not item.get("derived"):
            findings.append(_finding(entity_id, "INFERENCE_MARKED_OBSERVED", "HIGH",
                "An inferred fact is not identified as derived.", item.get("id"),
                "Mark the fact derived or replace it with direct evidence."))
        stale_after = item.get("stale_after")
        try:
            stale_time = datetime.fromisoformat(str(stale_after).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            stale_time = None
        if stale_time is not None and stale_time < evaluated_at.astimezone(timezone.utc):
            findings.append(_finding(entity_id, "STALE_ENRICHMENT", "MEDIUM",
                "A changeable enrichment fact is past its refresh horizon.",
                {"fact_id": item.get("id"), "stale_after": stale_after},
                "Refresh this fact from its permitted public source before relying on it."))

    for field in enrichment.get("conflicted_fields") or []:
        findings.append(_finding(entity_id, "CONFLICTING_FACTS", "MEDIUM",
            f"Sources disagree about {field}.",
            [item.get("id") for item in facts if item.get("field") == field],
            "Research the competing sources; preserve all candidates until resolved."))

    canonical_name = (record.get("business_profile") or {}).get("company")
    observed_names = [
        item for item in facts
        if item.get("field") == "organization.business_name" and item.get("source") == "schema.org"
    ]
    canonical_normalized = _normalized_name(canonical_name)
    if canonical_normalized and observed_names:
        similarities = [
            (SequenceMatcher(None, canonical_normalized, _normalized_name(item.get("value"))).ratio(), item)
            for item in observed_names if _normalized_name(item.get("value"))
        ]
        best_similarity, best_fact = max(similarities, default=(1.0, {}), key=lambda pair: pair[0])
        if best_similarity < 0.65 and record.get("prospect_type") != "Funeral Home Prospect":
            findings.append(_finding(entity_id, "ORGANIZATION_WEBSITE_MISMATCH", "HIGH",
                "The discovered organization name is not supported by the fetched website identity.",
                {"discovered_name": canonical_name, "closest_observed_name": best_fact.get("value"),
                 "similarity": round(best_similarity, 2), "source_url": best_fact.get("source_url")},
                "Resolve the website/entity mapping before scoring, CRM synchronization, or outreach."))

    contacts = record.get("contact_intelligence") or record.get("contacts") or {}
    email_items = contacts.get("email_validation") or []
    for item in email_items:
        email = str(item.get("email") or item.get("normalized") or "")
        if email and entity_id and _email_domain(email) not in {entity_id, f"www.{entity_id}"}:
            sources = [source for source in contacts.get("email_sources") or []
                if str(source.get("value") or "").casefold() == email.casefold()]
            first_party = any(
                source.get("source_type") in {"page_text", "structured_data"}
                and (urlsplit(str(source.get("source_url") or "")).hostname or "").lower().removeprefix("www.") == entity_id
                for source in sources
            )
            if first_party:
                findings.append(_finding(entity_id, "EMAIL_DOMAIN_FIRST_PARTY_CONFIRMED", "LOW",
                    "A cross-domain contact address is published on the organization's own website.",
                    {"email": email, "company_domain": entity_id,
                     "source_urls": sorted({source.get("source_url") for source in sources if source.get("source_url")})},
                    "Retain the attribution with its first-party source; investigate parent ownership separately."))
            else:
                findings.append(_finding(entity_id, "EMAIL_DOMAIN_MISMATCH", "MEDIUM",
                    "A contact email domain does not match the organization domain.",
                    {"email": email, "company_domain": entity_id, "state": item.get("verification_state")},
                    "Confirm the contact-to-company attribution before CRM synchronization."))
        if item.get("verification_state") == "DNS_VALID" and item.get("deliverability") not in {None, "NOT_CHECKED"}:
            findings.append(_finding(entity_id, "DNS_CLAIMED_DELIVERABLE", "HIGH",
                "DNS validation is being represented as mailbox deliverability.", item,
                "Reset deliverability to NOT_CHECKED pending external mailbox verification."))

    for item in contacts.get("phone_verification") or []:
        reachability = item.get("reachability", item.get("reachable"))
        if item.get("verification_state") == "METADATA_VALIDATED" and reachability not in {None, "NOT_CHECKED"}:
            findings.append(_finding(entity_id, "METADATA_CLAIMED_REACHABLE", "HIGH",
                "Phone metadata is being represented as live reachability.", item,
                "Reset reachability to NOT_CHECKED pending an authorized external lookup."))

    people = contacts.get("people") or []
    seen_people = set()
    for person in people:
        key = (str(person.get("name", "")).casefold(), str(person.get("title", "")).casefold())
        if key in seen_people and any(key):
            findings.append(_finding(entity_id, "DUPLICATE_CONTACT", "LOW",
                "The same named contact and title occur more than once.", key,
                "Deduplicate by normalized name, role, company, and evidence source."))
        seen_people.add(key)

    role_facts = [item for item in facts if item.get("field") == "contact.role_category"]
    for item in role_facts:
        source_url = item.get("source_url", "")
        if not source_url or not urlsplit(source_url).hostname:
            findings.append(_finding(entity_id, "DECISION_ROLE_WITHOUT_SOURCE", "HIGH",
                "A derived decision-maker category lacks a usable evidence URL.", item.get("id"),
                "Return the contact to research until the public title source is available."))

    score = record.get("executive_priority_score", record.get("sales_priority_score", 0)) or 0
    if score >= 70 and not facts and not contacts.get("emails") and not contacts.get("phones"):
        findings.append(_finding(entity_id, "HIGH_SCORE_WEAK_EVIDENCE", "HIGH",
            "A high-priority score has no enrichment or contact evidence.", {"score": score},
            "Hold CRM synchronization and inspect the scoring inputs."))

    unique = {item["id"]: item for item in findings}
    ordered = sorted(unique.values(), key=lambda item: ({"HIGH": 0, "MEDIUM": 1, "LOW": 2}[item["severity"]], item["code"]))
    return {
        "agent": AGENT,
        "agent_version": VERSION,
        "evaluated_at": iso(evaluated_at),
        "status": "NEEDS_REVIEW" if any(item["requires_review"] for item in ordered) else "PASSED",
        "findings": ordered,
        "finding_count": len(ordered),
        **readiness_from_findings(ordered),
    }


def evaluate_dataset_quality(records: Iterable[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Return cross-entity review findings without selecting a canonical winner."""
    records = list(records)
    findings: Dict[str, List[Dict[str, Any]]] = {str(item.get("domain", "")): [] for item in records}
    names: Dict[str, set[str]] = {}
    addresses: Dict[str, set[str]] = {}
    for record in records:
        domain = str(record.get("domain") or "")
        profile = record.get("business_profile") or {}
        for name in [profile.get("company"), *(profile.get("business_names") or [])]:
            normalized = " ".join(str(name or "").casefold().split())
            if normalized:
                names.setdefault(normalized, set()).add(domain)
        for location in profile.get("locations") or []:
            if not isinstance(location, dict):
                continue
            normalized = "|".join(
                " ".join(str(location.get(key) or "").casefold().split())
                for key in ("address", "city", "province", "country")
            ).strip("|")
            if normalized:
                addresses.setdefault(normalized, set()).add(domain)

    for value, domains in names.items():
        if len(domains) > 1:
            for domain in domains:
                findings[domain].append(_finding(domain, "POSSIBLE_DUPLICATE_ORGANIZATION", "MEDIUM",
                    "The same normalized business name appears under multiple domains.",
                    {"normalized_name": value, "domains": sorted(domains)},
                    "Resolve whether these are duplicates, branches, or an ownership network."))
    for value, domains in addresses.items():
        if len(domains) > 1:
            for domain in domains:
                findings[domain].append(_finding(domain, "SHARED_ADDRESS_REVIEW", "MEDIUM",
                    "Multiple organizations share a normalized public address.",
                    {"normalized_address": value, "domains": sorted(domains)},
                    "Confirm whether the records are branches, co-located businesses, or duplicates."))
    return findings
