#!/usr/bin/env python3
"""Merge explicit branch contacts from the isolated zero-page retry crawl."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from audit_merge_falconer_v7 import metrics, write_json


BASE = Path("data/generated/directory_955")
PAGES = BASE / "zero_page_retry_v1/pages.json"
REPORT = BASE / "zero_page_retry_v1/crawl_report.json"
SOURCE = BASE / "full_955_enrichment_v13/full_955_enrichment.json"
AUDIT = BASE / "zero_page_retry_contact_audit_v1"
OUTPUT = BASE / "full_955_enrichment_v14"
CRM = Path("data/crm.sqlite")
CRM_SHA256 = "c06bee94b72a8bbde83e1755a9897800543f038e255e6e2db72cca744a736b9e"

RECOVERIES = [
    ("CFI-0029", "https://armstrong.frontrunnerpro.com/Contact_Information_-16115.html", "phone", "+19054334711", "Armstrong Funeral Home Limited\n124 King Street East, , Oshawa, ON\nL1H 1B6, CA\nPhone Number:\n905-433-4711"),
    ("CFI-0029", "https://armstrong.frontrunnerpro.com/Contact_Information_-16115.html", "email", "directors@armstrongfh.ca", "Email Address:\ndirectors@armstrongfh.ca"),
    ("CFI-0429", "https://catholic-cemeteries.frontrunnerpro.com/Contact_Us_1212850.html", "phone", "+19058897467", "HOLY CROSS  CATHOLIC CEMETERY & FUNERAL HOME\n8361 Yonge Street\nThornhill, ON\nL3T 2C7\n(905) 889-7467"),
    ("CFI-0386", "https://www.hallfuneralservices.ca/contact-us", "phone", "+13066348233", "Hall Funeral Services - Estevan\n1506 - 4th Street\nEstevan\nSK\nS4A 0X6\n306-634-8233"),
    ("CFI-0387", "https://www.hallfuneralservices.ca/contact-us", "phone", "+13064526020", "Hall Funeral Services - Redvers\n13 Souris Avenue\nRedvers\n,\nSK\nS0C 2H0\n306-452-6020"),
    ("CFI-0753", "https://roadhouseandrose.frontrunnerpro.com/Contact_Information_689074.html", "phone", "+19058956631", "Roadhouse & Rose Funeral Home\n157 Main Street South\nNewmarket, ON\nL3Y-3Y9\ntel (905) 895-6631"),
    ("CFI-0753", "https://roadhouseandrose.frontrunnerpro.com/Contact_Information_689074.html", "email", "wes@roadhouseandrose.com", "Wes Playter, Funeral Director / Co-Owner / Manager\nEmail:\nwes@roadhouseandrose.com"),
    ("CFI-0818", "https://www.staceysfuneralhome.ca/contact-us.html", "phone", "+17092568585", "Stacey's Funeral Home\n60 Roe Ave\nP.O. Box 539\nGander,\nNL\nA1V 2E1\nPhone:\n709-256-8585"),
]


def main() -> None:
    crm_before = hashlib.sha256(CRM.read_bytes()).hexdigest()
    pages = {row["url"]: row for row in json.loads(PAGES.read_text())}
    report = json.loads(REPORT.read_text())
    canonical = json.loads(SOURCE.read_text())
    by_id = {row["directory_record_id"]: row for row in canonical}
    safe = []
    for record_id, url, kind, value, marker in RECOVERIES:
        page = pages[url]
        assert " ".join(marker.split()) in " ".join(page["text"].split())
        record = by_id[record_id]
        safe.append({
            "directory_record_id": record_id, "company": record["company"],
            "city": record["city"], "province": record["province"],
            "type": kind, "value": value, "source_url": url,
            "source_file": str(PAGES),
            "source_text_sha256": hashlib.sha256(page["text"].encode()).hexdigest(),
            "source_html_sha256": hashlib.sha256(page["html"].encode()).hexdigest(),
            "classification": "BRANCH_SAFE", "evidence_marker": marker,
            "branch_attribution": "Value is inside the target business location/contact block.",
        })
    safe_ids = {row["directory_record_id"] for row in safe}
    assert len(safe) == 8 and len(safe_ids) == 6
    shared = [
        {"domain": "hallfuneralservices.ca", "type": "email", "value": "info@hallfuneralservices.ca", "classification": "ORGANIZATION_SHARED", "reason": "repeated in Estevan and Redvers blocks"},
        {"domain": "staceysfuneralhome.ca", "type": "email", "value": "staceysfuneralhome@hotmail.com", "classification": "ORGANIZATION_SHARED", "reason": "repeated in Gander and Carmanville blocks"},
        {"domain": "catholic-cemeteries.frontrunnerpro.com", "type": "email", "value": "info@cc-fs.ca", "classification": "ORGANIZATION_SHARED", "reason": "central business office/footer email"},
    ]
    rejected = [
        {"classification": "REJECTED", "values": ["+19054333863", "+19058954747", "+17092567606"], "reason": "explicit fax numbers"},
        {"classification": "REJECTED", "values": ["+18882568585", "+18009744619"], "reason": "toll-free alternatives not needed as branch primary"},
        {"classification": "REJECTED", "domains": ["centralfuneral.frontrunnerpro.com", "gordonmonkfh.frontrunnerpro.com", "grahamgiddy.frontrunnerpro.com", "hwalser.frontrunnerpro.com", "ostrandersfuneral.frontrunnerpro.com", "pilonfamilyfuneralhome.frontrunnerpro.com", "reynoldsfuneralhome.frontrunnerpro.com"], "reason": "obituary-only, vendor, or wrong-identity evidence"},
    ]
    write_json(AUDIT / "branch_safe_contacts.json", safe)
    write_json(AUDIT / "organization_shared_contacts.json", shared)
    write_json(AUDIT / "rejected_contacts.json", rejected)
    write_json(AUDIT / "remaining_zero_page_domains.json", sorted(report["failed_domains"]))

    before = metrics(canonical)
    assert before == {
        "businesses_with_email": 159, "businesses_with_phone": 311,
        "businesses_with_staff": 138, "businesses_with_decision_maker": 111,
        "businesses_with_any_safe_contact": 312, "email_values": 271,
        "phone_values": 610, "named_staff": 705, "named_decision_makers": 270,
    }
    output = deepcopy(canonical)
    out_by_id = {row["directory_record_id"]: row for row in output}
    changed = []
    for record_id in sorted(safe_ids):
        record = out_by_id[record_id]
        enrichment = record["branch_safe_enrichment"]
        assert not enrichment["has_any_contact"]
        added_emails, added_phones = [], []
        for item in (row for row in safe if row["directory_record_id"] == record_id):
            value = {
                "value": item["value"], "source_url": item["source_url"],
                "source_file": item["source_file"],
                "source_text_sha256": item["source_text_sha256"],
                "source_html_sha256": item["source_html_sha256"],
                "evidence_class": "explicit_branch_contact_block",
                "reason": f"{item['type']}_inside_target_location_and_contact_block",
            }
            enrichment[f"{item['type']}s"].append(value)
            enrichment[f"has_{item['type']}"] = True
            (added_emails if item["type"] == "email" else added_phones).append(value)
        enrichment["has_any_contact"] = True
        enrichment["recovery_provenance"] = [{
            "pipeline": "zero_page_retry_contact_audit_v1",
            "classification": "BRANCH_SAFE", "method": "cached_explicit_location_block",
        }]
        changed.append({
            "directory_record_id": record_id, "company": record["company"],
            "city": record["city"], "province": record["province"],
            "added_emails": added_emails, "added_phones": added_phones,
            "staff_added": [], "decision_makers_added": [],
        })
    after = metrics(output)
    expected = dict(before)
    expected.update({
        "businesses_with_email": 161, "businesses_with_phone": 317,
        "businesses_with_any_safe_contact": 318, "email_values": 273,
        "phone_values": 616,
    })
    assert after == expected
    unresolved = [row for row in output if not row["branch_safe_enrichment"]["has_any_contact"]]
    assert len(output) == 955 and len({row["directory_record_id"] for row in output}) == 955
    assert len(unresolved) == 637 and 318 + len(unresolved) == 955
    summary = {
        "master_records": 955, "source": "full_955_enrichment_v13",
        "merge_source": "zero_page_retry_contact_audit_v1",
        "retry_domains": 38, "recovered_domains": 12, "recovered_pages": 58,
        "branch_safe_businesses": 6, "branch_safe_values": 8,
        "remaining_zero_page_domains": len(report["failed_domains"]),
        "merged_records": sorted(safe_ids), "before": before, "after": after,
        "net_gain": {key: after[key] - before[key] for key in before},
        "remaining_without_branch_safe_contact_or_staff": 637,
        "network_requests_in_merge": 0, "langsearch_requests": 0, "crm_writes": 0,
        "invariants": {
            "master_is_955": True, "unique_directory_record_ids": True,
            "only_explicit_location_blocks_merged": True,
            "shared_emails_not_merged": True, "fax_and_toll_free_rejected": True,
            "obituary_vendor_wrong_identity_rejected": True,
            "staff_unchanged": True, "decision_makers_unchanged": True,
            "resolved_plus_unresolved_is_955": True,
        },
    }
    write_json(AUDIT / "summary.json", summary)
    write_json(OUTPUT / "full_955_enrichment.json", output)
    write_json(OUTPUT / "changed_records.json", changed)
    write_json(OUTPUT / "organization_shared_contacts.json", shared)
    write_json(OUTPUT / "summary.json", summary)
    write_json(OUTPUT / "unresolved_after_merge.json", unresolved)
    crm_after = hashlib.sha256(CRM.read_bytes()).hexdigest()
    assert crm_before == crm_after == CRM_SHA256
    print(json.dumps({"summary": summary, "crm_sha256": crm_after}, indent=2))


if __name__ == "__main__":
    main()
