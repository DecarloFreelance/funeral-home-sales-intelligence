#!/usr/bin/env python3
"""Materialize V17 from V16 using only reviewed V17 recovery evidence."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from audit_merge_falconer_v7 import metrics, write_json
from verify_langsearch_recovery_v2 import enforce_first_party

BASE = Path("data/generated/directory_955")
SOURCE = BASE / "full_955_enrichment_v16/full_955_enrichment.json"
VERIFIED = BASE / "langsearch_unverified_v2/verification/verified_websites.json"
PAGES = BASE / "v17_verified_recovery_v1/migration_pages.json"
OUTPUT = BASE / "full_955_enrichment_v17"
CRM = Path("data/crm.sqlite")
SOURCE_SHA256 = "78dceed53888b09815af77953cea6e2439021d238d63e70f63a290e3ad806c48"
CRM_SHA256 = "c06bee94b72a8bbde83e1755a9897800543f038e255e6e2db72cca744a736b9e"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def materialize(output: Path = OUTPUT) -> dict:
    if sha256(SOURCE) != SOURCE_SHA256 or sha256(CRM) != CRM_SHA256:
        raise ValueError("Immutable V16 or CRM source drift detected")
    original = json.loads(SOURCE.read_text(encoding="utf-8"))
    result = deepcopy(original)
    by_id = {row["directory_record_id"]: row for row in result}
    verified = [enforce_first_party(row) for row in json.loads(VERIFIED.read_text(encoding="utf-8"))]
    verified = [row for row in verified if row.get("status") in {"VERIFIED", "VERIFIED_HIGH"}]
    website_changes, preserved_reviewed = [], []
    for evidence in verified:
        row = by_id[evidence["directory_record_id"]]
        if not row.get("website") and row.get("website_status") == "no_signal":
            row["website"] = evidence["website"]
            row["website_status"] = "verified"
            row["website_verification"] = {
                "source": "langsearch_v2_plus_first_party_verification",
                "confidence": evidence["confidence"], "score": evidence["verification_score"],
                "evidence": evidence["evidence"],
                "reconciliation_provenance": evidence.get("reconciliation_provenance"),
            }
            website_changes.append(evidence["directory_record_id"])
        else:
            preserved_reviewed.append(evidence["directory_record_id"])

    # Exact Winnipeg block reviewed from the verified Neil Bardal migration crawl.
    page = next(row for row in json.loads(PAGES.read_text(encoding="utf-8"))
                if row["url"].endswith("contact-our-Manitoba-funeral-homes"))
    marker = "204-949-2200\nFax:\n204-694-9494\nEmail Us\nFor general inquiries & questions,\ncontact us via email.\ninfo@nbardal.mb.ca\nVisit Us\n3030 Notre Dame Avenue\nWinnipeg"
    if marker not in page["text"]:
        raise ValueError("CFI-0658 Winnipeg evidence block drift")
    enrichment = by_id["CFI-0658"]["branch_safe_enrichment"]
    additions = {
        "emails": {"value": "info@nbardal.mb.ca", "source_url": page["url"],
                   "source_text_sha256": hashlib.sha256(page["text"].encode()).hexdigest(),
                   "evidence_class": "explicit_winnipeg_location_block",
                   "evidence_marker": marker},
        "phones": {"value": "+12049492200", "source_url": page["url"],
                   "source_text_sha256": hashlib.sha256(page["text"].encode()).hexdigest(),
                   "evidence_class": "explicit_winnipeg_location_block",
                   "evidence_marker": marker},
    }
    for key, item in additions.items():
        if item["value"] not in {value["value"] for value in enrichment[key]}:
            enrichment[key].append(item)
        enrichment[f"has_{key[:-1]}"] = True
    enrichment["has_any_contact"] = True
    enrichment["recovery_provenance"] = [{"pipeline": "v17_verified_recovery_v1",
        "classification": "BRANCH_SAFE", "method": "explicit_winnipeg_location_block"}]

    changed_ids = [new["directory_record_id"] for old, new in zip(original, result) if old != new]
    before, after = metrics(original), metrics(result)
    provinces = sorted({row.get("province") for row in result if row.get("province")})
    fact_count = sum(len((row.get("branch_safe_enrichment") or {}).get(key) or [])
                     for row in result for key in ("emails", "phones", "staff"))
    summary = {
        "version": "V17", "source": "full_955_enrichment_v16", "total_organizations": len(result),
        "verified_website_count": sum(row.get("website_status") == "verified" for row in result),
        "langsearch_verified_count": len(verified), "newly_recovered_websites_vs_v16": len(website_changes),
        "preserved_existing_reviewed_website_ids": preserved_reviewed,
        "contact_count": after["businesses_with_any_safe_contact"], "email_count": after["email_values"],
        "phone_count": after["phone_values"], "staff_count": after["named_staff"],
        "decision_maker_count": after["named_decision_makers"], "province_coverage": provinces,
        "evidence_fact_count": fact_count, "review_unresolved_website_count": 399,
        "records_changed_from_v16": len(changed_ids), "records_unchanged_from_v16": len(result)-len(changed_ids),
        "changed_record_ids": changed_ids, "website_changed_record_ids": website_changes,
        "branch_safe_contact_recoveries": ["CFI-0658"], "before": before, "after": after,
        "crm_writes": 0, "outreach_actions": 0,
        "invariants": {"unique_directory_record_ids": len({r["directory_record_id"] for r in result}) == 955,
                       "v16_unchanged": sha256(SOURCE) == SOURCE_SHA256,
                       "crm_unchanged": sha256(CRM) == CRM_SHA256,
                       "reviewed_canonical_not_overwritten": "CFI-0756" in preserved_reviewed},
    }
    write_json(output / "full_955_enrichment.json", result)
    write_json(output / "changed_records.json", [row for row in result if row["directory_record_id"] in changed_ids])
    write_json(output / "summary.json", summary)
    if sha256(SOURCE) != SOURCE_SHA256 or sha256(CRM) != CRM_SHA256:
        raise RuntimeError("Immutable input changed during V17 materialization")
    return summary


if __name__ == "__main__":
    print(json.dumps(materialize(), indent=2))
