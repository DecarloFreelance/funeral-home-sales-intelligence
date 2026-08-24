#!/usr/bin/env python3
"""Build internal, evidence-traceable commercial audit candidates.

This module deliberately does not send outreach or write CRM state. It treats
the durable enrichment facts as authoritative and retains legacy scores only as
labelled internal context, never as ranking inputs or customer-facing claims.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List
from urllib.parse import urlsplit

from automation.orchestrator import AgentOrchestrator
from enrichment.quality import approved_for_commercial_use


VERSION = "1.0.0"
POSITIVE_FIELDS = {
    "digital.online_arrangements": "online arrangement capability",
    "digital.livestream": "livestream or webcast capability",
    "business.careers_page": "careers information",
    "organization.social_profile": "public social profile",
}


def _domain(page: Dict[str, Any]) -> str:
    discovery = page.get("discovery") or {}
    return str(discovery.get("queue_domain") or urlsplit(page.get("url", "")).hostname or "").lower().removeprefix("www.")


def _facts(record: Dict[str, Any], field: str) -> List[Dict[str, Any]]:
    return [item for item in (record.get("enrichment") or {}).get("facts") or [] if item.get("field") == field]


def _references(facts: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "fact_id": item["id"],
            "source_url": item.get("source_url", ""),
            "observed_at": item.get("observed_at"),
            "verification_state": item.get("verification_state"),
            "confidence": item.get("confidence"),
        }
        for item in facts
    ]


def _safe(record: Dict[str, Any]) -> bool:
    return approved_for_commercial_use(record, outreach=True)


def build_shortlist(records: Iterable[Dict[str, Any]], pages: Iterable[Dict[str, Any]], *, limit=25) -> List[Dict[str, Any]]:
    pages_by_domain: Dict[str, List[Dict[str, Any]]] = {}
    for page in pages:
        pages_by_domain.setdefault(_domain(page), []).append(page)
    candidates = []
    for record in records:
        domain = str(record.get("domain") or "").lower().removeprefix("www.")
        if not domain or not _safe(record):
            continue
        website = _facts(record, "organization.website")
        email = _facts(record, "contact.public_email")
        phone = _facts(record, "contact.public_phone")
        people = _facts(record, "contact.person")
        roles = _facts(record, "contact.role_category")
        scanned_pages = sorted({str(page.get("url") or "") for page in pages_by_domain.get(domain, []) if page.get("url")})
        if not website or not scanned_pages or not (email or phone):
            continue

        opportunities = []
        for field, label in POSITIVE_FIELDS.items():
            if not _facts(record, field):
                opportunities.append({
                    "field": field,
                    "interpretation": f"Our bounded scan did not detect {label}.",
                    "confidence": "LIMITED_BY_SCAN_SCOPE",
                    "evidence": {"pages_checked": scanned_pages},
                })
        if not opportunities:
            continue

        contact_points = 2 * bool(email) + bool(phone) + 2 * bool(people) + 2 * bool(roles)
        evidence_points = min(5, len(scanned_pages)) + min(4, len(website) + len(email) + len(phone))
        opportunity_points = min(4, len(opportunities))
        rank_score = contact_points * 10 + evidence_points * 3 + opportunity_points * 4
        profile = record.get("business_profile") or {}
        reasons = ["CRM and outreach safety checks passed", "A successfully crawled first-party website is retained"]
        if email:
            reasons.append("A public business email has local/DNS validation evidence")
        if phone:
            reasons.append("A public business phone has parsing/metadata evidence")
        if people:
            reasons.append("A named professional contact is backed by a public source")
        reasons.append(f"{len(opportunities)} bounded-scan opportunity observations are available")
        evidence = _references([*website, *email, *phone, *people, *roles])
        candidates.append({
            "organization_id": domain,
            "organization_name": profile.get("company") or domain,
            "province": profile.get("province") or next((x.get("province") for x in profile.get("locations", []) if x.get("province")), ""),
            "rank_score": rank_score,
            "selection_reasons": reasons,
            "contact": {
                "emails": [item.get("value") for item in email],
                "phones": [item.get("value") for item in phone],
                "named_contacts": [item.get("value") for item in people],
            },
            "observed_opportunities": opportunities,
            "evidence_references": evidence,
            "pages_checked": scanned_pages,
            "safety": {"crm_sync_safe": True, "outreach_ready": True, "outreach_sent": False, "crm_synced": False},
            "legacy_score_internal_only": record.get("executive_priority_score", record.get("sales_priority_score")),
        })
    return sorted(candidates, key=lambda item: (-item["rank_score"], item["organization_id"]))[:limit]


def build_prototypes(shortlist: Iterable[Dict[str, Any]], *, limit=5) -> List[Dict[str, Any]]:
    prototypes = []
    for item in list(shortlist)[:limit]:
        observed = [{
            "statement": "A public first-party website was successfully scanned.",
            "evidence": item["pages_checked"],
            "confidence": "LOCALLY_VALIDATED",
        }]
        if item["contact"]["emails"]:
            observed.append({
                "statement": "A public business email was observed; DNS validation does not prove mailbox reachability.",
                "evidence": [value for value in item["evidence_references"] if value["fact_id"]],
                "confidence": "LOCAL_OR_DNS_VALIDATION_ONLY",
            })
        prototypes.append({
            "organization_id": item["organization_id"],
            "organization_name": item["organization_name"],
            "title": "Internal Funeral Home Digital Growth Audit Prototype",
            "observed_facts": observed,
            "interpreted_opportunities": item["observed_opportunities"],
            "recommended_next_action": "Operator should verify each cited page before preparing a personalized, approval-gated outreach draft.",
            "limitations": [
                "A feature not detected during this bounded scan may exist on an unscanned or dynamically rendered page.",
                "No revenue, ranking, compliance, or causal business-impact claim is made.",
                "This prototype does not authorize or send outreach.",
            ],
        })
    return prototypes


def build_package(records, pages, *, shortlist_limit=25, prototype_limit=5):
    shortlist = build_shortlist(records, pages, limit=shortlist_limit)
    payload = {
        "schema_version": 1,
        "generator": "commercial_readiness",
        "generator_version": VERSION,
        "shortlist": shortlist,
        "prototypes": build_prototypes(shortlist, limit=prototype_limit),
        "safety": {"outreach_performed": False, "crm_write_performed": False},
    }
    stable = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    payload["package_id"] = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:24]
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate an internal evidence-backed commercial shortlist and audit prototypes.")
    parser.add_argument("--results", type=Path, default=Path("data/generated/scale/enriched_results.json"))
    parser.add_argument("--pages", type=Path, default=Path("data/generated/scale/pages.json"))
    parser.add_argument("--output", type=Path, default=Path("data/generated/scale/commercial_readiness.json"))
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--prototype-limit", type=int, default=5)
    args = parser.parse_args(argv)
    records = json.loads(args.results.read_text(encoding="utf-8"))
    pages = json.loads(args.pages.read_text(encoding="utf-8"))
    package = build_package(records, pages, shortlist_limit=args.limit, prototype_limit=args.prototype_limit)
    AgentOrchestrator._atomic_json(args.output, package)
    print(f"Commercial candidates={len(package['shortlist'])} prototypes={len(package['prototypes'])} writes=internal-only")


if __name__ == "__main__":
    main()
