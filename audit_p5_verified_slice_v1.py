#!/usr/bin/env python3
"""Fail-closed attribution audit for the 32-record P5 verified-site slice."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from audit_merge_falconer_v7 import write_json


BASE = Path("data/generated/directory_955")
RECON = BASE / "offline_recovery_p5_reconciled_v1"
BATCH = Path("data/generated/batches/9b03bfd72514657f")
V10 = BASE / "full_955_enrichment_v10/full_955_enrichment.json"
CRM = Path("data/crm.sqlite")


def main() -> None:
    crm_before = hashlib.sha256(CRM.read_bytes()).hexdigest()
    verified = json.loads((RECON / "verified_no_contact.json").read_text())
    exclusions = json.loads((RECON / "excluded_wrong_or_third_party.json").read_text())
    source = json.loads((RECON / "verified_slice_crawler_source.json").read_text())
    pages = json.loads((BATCH / "pages.json").read_text())
    report = json.loads((BATCH / "crawl_report.json").read_text())
    canonical = json.loads(V10.read_text())
    assert len(verified) == 32 and len(source) == 29 and len(exclusions) == 3
    assert report["queued_domains"] == 29 and report["successful_domains"] == 16
    assert len(report["failed_domains"]) == 13 and sum(report["attempt_outcomes"].values()) == 232
    assert report["attempt_outcomes"]["CROSS_DOMAIN_REDIRECT"] == 7

    email_re = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
    phone_re = re.compile(r"(?:\+?1[-. ()]*)?(?:\d{3}[-. ()]*){2}\d{4}")
    signals = []
    for page in pages:
        for value in sorted(set(email_re.findall(page.get("text", "")))):
            signals.append({"type": "email", "value": value.lower(), "url": page["url"]})
        for value in sorted(set(phone_re.findall(page.get("text", "")))):
            signals.append({"type": "phone", "value": value, "url": page["url"]})
    assert {(row["type"], row["value"]) for row in signals} == {
        ("email", "success@frontrunner360.com"),
        ("phone", "905) 937-4444"),
    }
    rejected = [
        {
            "directory_record_id": "CFI-0146", "type": "email",
            "value": "success@frontrunner360.com", "classification": "REJECT_VENDOR_CONTACT",
            "reason": "FrontRunner Success Coach support address on an admin runtime page.",
        },
        {
            "directory_record_id": "CFI-0873", "type": "phone",
            "value": "+19059374444", "classification": "REJECT_WRONG_BUSINESS",
            "reason": "Garden City closure notice identifies the number as George Darte, not Tri-City Cremation Services.",
        },
    ]
    status_by_domain = {row["domain"]: row for row in report["leads"]}
    mapping_by_id = {row["directory_record_id"]: row for row in source}
    excluded_by_id = {row["directory_record_id"]: row for row in exclusions}
    classifications = []
    for row in verified:
        record_id = row["directory_record_id"]
        if record_id in excluded_by_id:
            classification = "QUARANTINED_MAPPING"
            reason = excluded_by_id[record_id]["reason"]
        else:
            domain = mapping_by_id[record_id]["website"].split("//", 1)[1].strip("/")
            status = status_by_domain[domain]
            classification = "REVIEW"
            reason = f"NO_BRANCH_SAFE_CONTACT:{status['status']}:{status.get('reason', 'NO_CONTACT_SIGNAL')}"
            if record_id == "CFI-0146":
                reason = "VENDOR_SUPPORT_EMAIL_ONLY"
            elif record_id == "CFI-0873":
                reason = "WRONG_BUSINESS_PHONE_ON_GARDEN_CITY_CLOSURE_NOTICE"
        classifications.append({
            "directory_record_id": record_id, "company": row["company"],
            "city": row["city"], "classification": classification, "reason": reason,
        })
    assert len(classifications) == 32
    canonical_by_id = {row["directory_record_id"]: row for row in canonical}
    assert all(not canonical_by_id[row["directory_record_id"]]["branch_safe_enrichment"]["has_any_contact"] for row in classifications)
    summary = {
        "verified_slice_businesses": 32, "crawl_source_businesses": 29,
        "excluded_before_crawl": 3, "successful_domains": 16, "failed_domains": 13,
        "crawl_attempts": 232, "crawl_pages_reported": report["pages"],
        "raw_contact_signals": 2, "branch_safe_businesses": 0,
        "rejected_contact_signals": 2, "unresolved_businesses": 32,
        "canonical_source": "full_955_enrichment_v10", "merged_records": 0,
        "langsearch_requests": 0, "crm_writes": 0,
        "invariants": {
            "verified_slice_conservation": True,
            "vendor_support_email_blocked": True,
            "wrong_business_closure_phone_blocked": True,
            "known_bad_mappings_quarantined": True,
            "cross_domain_redirects_failed_closed": True,
            "nothing_merged": True,
        },
    }
    write_json(RECON / "verified_slice_classifications.json", classifications)
    write_json(RECON / "verified_slice_rejected_contacts.json", rejected)
    write_json(RECON / "verified_slice_audit_summary.json", summary)
    crm_after = hashlib.sha256(CRM.read_bytes()).hexdigest()
    assert crm_before == crm_after == "c06bee94b72a8bbde83e1755a9897800543f038e255e6e2db72cca744a736b9e"
    print(json.dumps({"summary": summary, "crm_sha256": crm_after}, indent=2))


if __name__ == "__main__":
    main()
