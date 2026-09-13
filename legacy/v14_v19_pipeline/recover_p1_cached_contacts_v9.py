#!/usr/bin/env python3
"""Audit remaining P1 cached pages and materialize branch-safe phones into V9."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path

from audit_merge_falconer_v7 import metrics, write_json


BASE = Path("data/generated/directory_955")
TRIAGE = BASE / "offline_recovery_75_fetch_triage_v1"
PAGES = Path("data/generated/batches/4a7aa3af0c4f8a44/pages.json")
V8 = BASE / "full_955_enrichment_v8/full_955_enrichment.json"
AUDIT = BASE / "offline_recovery_p1_cached_contacts_v1"
V9 = BASE / "full_955_enrichment_v9"
CRM = Path("data/crm.sqlite")

# Every marker includes the branch name/address context and its paired phone.
RECOVERIES = [
    ("CFI-0310", "https://www.frenettefuneralhome.com/contact-us", "+15065323297", "Shediac\n(506) 532-3297"),
    ("CFI-0051", "https://barclayupgrade.funeraltechweb.com/contact-us/", "+16133422792", "137 Pearl Street East\nBrockville, Ontario\nK6V 1R2"),
    ("CFI-0174", "https://www.cooperativefuneraire.ca/contactez-nous", "+17058554448", "Chelmsford\n705-855-4448\nChelmsford\n4691 Route régionale 15"),
    ("CFI-0172", "https://www.cooperativefuneraire.ca/contactez-nous", "+17059697272", "Hanmer\n705-969-7272\nHanmer\n4570 rue St-Joseph"),
    ("CFI-0394", "https://www.haskettfh.com/contact-us/", "+15192373532", "Dashwood:\n519-237-3532"),
    ("CFI-0395", "https://www.haskettfh.com/contact-us/", "+15192351220", "Exeter:\n519-235-1220"),
    ("CFI-0396", "https://www.haskettfh.com/contact-us/", "+15192274211", "Lucan:\n519-227-4211"),
    ("CFI-0397", "https://www.haskettfh.com/contact-us/", "+15195271390", "Seaforth:\n519-527-1390"),
    ("CFI-0067", "https://beaulac.funeraltechweb.com/40/Contact-Us.html", "+13068833500", "Spiritwood\n113 6th Street West\nSpiritwood, SK\nS0J 2M0\n1-306-883-3500"),
]


def main() -> None:
    crm_before = hashlib.sha256(CRM.read_bytes()).hexdigest()
    review_rows = json.loads((TRIAGE / "review_pages.json").read_text())
    weak_rows = json.loads((TRIAGE / "weak_pages.json").read_text())
    cohort = review_rows + weak_rows
    assert len(review_rows) == 10 and len(weak_rows) == 54 and len(cohort) == 64
    cohort_ids = {row["directory_record_id"] for row in cohort}
    recovery_ids = {item[0] for item in RECOVERIES}
    assert len(recovery_ids) == 9 and recovery_ids <= cohort_ids

    pages = json.loads(PAGES.read_text())
    by_url = {page["url"]: page for page in pages}
    canonical = json.loads(V8.read_text())
    records_by_id = {record["directory_record_id"]: record for record in canonical}
    safe = []
    for record_id, url, value, marker in RECOVERIES:
        page = by_url[url]
        text = page["text"]
        assert marker in text
        if record_id == "CFI-0051":
            # The rendered text flattens a two-column table. Prove that the
            # Brockville address and phone occupy the corresponding second cells.
            html = page["html"]
            assert re.search(
                r"<tr><td[^>]*>.*?Lansdowne, Ontario.*?</td>"
                r"<td[^>]*>.*?Brockville, Ontario.*?</td></tr>"
                r"<tr><td[^>]*>.*?659-2127.*?</td>"
                r"<td[^>]*>.*?342-2792.*?</td></tr>",
                html,
                re.DOTALL,
            )
        record = records_by_id[record_id]
        safe.append({
            "directory_record_id": record_id,
            "company": record["company"],
            "city": record["city"],
            "province": record["province"],
            "type": "phone",
            "value": value,
            "source_url": url,
            "source_file": str(PAGES),
            "source_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "source_html_sha256": hashlib.sha256(page["html"].encode()).hexdigest(),
            "classification": "BRANCH_SAFE",
            "branch_attribution": "Phone is paired with the target branch name/address in cached first-party page text.",
            "evidence_marker": marker,
        })

    shared = [
        {"value": "info@barclayfuneralhome.com", "type": "email", "record_ids": ["CFI-0051"], "reason": "homepage-level email; contact page contains two branches"},
        {"value": "generalmail@cooperativefuneraire.ca", "type": "email", "record_ids": ["CFI-0172", "CFI-0174"], "reason": "identical email repeated for Sudbury, Chelmsford, and Hanmer"},
        {"value": "[email protected]", "type": "email", "record_ids": ["CFI-0394", "CFI-0395", "CFI-0396", "CFI-0397"], "reason": "general email repeated across all Haskett locations"},
        {"value": "info@cropo.ca", "type": "email", "record_ids": ["CFI-0186", "CFI-0187", "CFI-0188"], "reason": "identical email repeated across two Winnipeg chapels; St. Andrews branch absent"},
    ]
    rejected = [
        {"value": "+16133421548", "type": "phone", "classification": "REJECT_FAX", "source_url": "https://barclayupgrade.funeraltechweb.com/contact-us/"},
        {"value": "+17055661324", "type": "phone", "classification": "REJECT_FAX", "source_url": "https://www.cooperativefuneraire.ca/contactez-nous"},
        {"value": "+15192353653", "type": "phone", "classification": "REJECT_FAX", "source_url": "https://www.haskettfh.com/contact-us/"},
    ]
    review = []
    for row in cohort:
        record_id = row["directory_record_id"]
        if record_id in recovery_ids:
            continue
        reason = "NO_EXPLICIT_TARGET_BRANCH_CONTACT_BLOCK_IN_CACHED_FIRST_PARTY_PAGES"
        if record_id in {"CFI-0186", "CFI-0187", "CFI-0188"}:
            reason = "CROPO_DIRECTORY_ROWS_CANNOT_BE_MAPPED_TO_TWO_WINNIPEG_CONTACT_BLOCKS"
        elif record_id in {"CFI-0129", "CFI-0130"}:
            reason = "CARDINAL_DIRECTORY_ROWS_CANNOT_BE_MAPPED_TO_ANNETTE_OR_BATHURST"
        elif record_id in {"CFI-0263", "CFI-0264"}:
            reason = "EVEREST_DIRECTORY_ROWS_CANNOT_BE_MAPPED_TO_WAVERLEY_OR_WESTFORT"
        elif "dignitymemorial.com" in str(row):
            reason = "DIGNITY_CITY_OR_OBITUARY_PAGE_LACKS_TARGET_BRANCH_CONTACT_BLOCK"
        review.append({
            "directory_record_id": record_id,
            "company": row["company"],
            "city": row["city"],
            "classification": "REVIEW",
            "reason": reason,
        })
    assert len(review) == 55 and len(safe) + len(review) == 64
    write_json(AUDIT / "branch_safe_contacts.json", safe)
    write_json(AUDIT / "organization_shared_contacts.json", shared)
    write_json(AUDIT / "rejected_contacts.json", rejected)
    write_json(AUDIT / "review_businesses.json", review)

    before = metrics(canonical)
    assert before == {
        "businesses_with_email": 158, "businesses_with_phone": 254,
        "businesses_with_staff": 138, "businesses_with_decision_maker": 111,
        "businesses_with_any_safe_contact": 255, "email_values": 270,
        "phone_values": 553, "named_staff": 705, "named_decision_makers": 270,
    }
    output = deepcopy(canonical)
    output_by_id = {record["directory_record_id"]: record for record in output}
    changed = []
    for item in safe:
        record = output_by_id[item["directory_record_id"]]
        enrichment = record["branch_safe_enrichment"]
        assert not enrichment["has_any_contact"] and not enrichment["phones"]
        phone = {
            "value": item["value"], "source_url": item["source_url"],
            "source_file": item["source_file"], "source_text_sha256": item["source_text_sha256"],
            "source_html_sha256": item["source_html_sha256"],
            "evidence_class": "explicit_branch_contact_block",
            "reason": "phone_paired_with_target_branch_name_or_address",
        }
        enrichment["phones"] = [phone]
        enrichment["has_phone"] = True
        enrichment["has_any_contact"] = True
        enrichment["recovery_provenance"] = [{
            "pipeline": "offline_recovery_p1_cached_contacts_v1",
            "classification": "BRANCH_SAFE",
            "method": "cached_named_branch_contact_block",
        }]
        changed.append({
            "directory_record_id": record["directory_record_id"], "company": record["company"],
            "city": record["city"], "province": record["province"],
            "added_emails": [], "added_phones": [phone], "staff_added": [], "decision_makers_added": [],
        })
    after = metrics(output)
    expected_after = dict(before)
    expected_after.update({
        "businesses_with_phone": 263,
        "businesses_with_any_safe_contact": 264,
        "phone_values": 562,
    })
    assert after == expected_after
    unresolved = [record for record in output if not record["branch_safe_enrichment"]["has_any_contact"]]
    assert len(output) == 955 and len({r["directory_record_id"] for r in output}) == 955
    assert len(unresolved) == 691 and 264 + len(unresolved) == 955
    summary = {
        "master_records": 955, "source": "full_955_enrichment_v8",
        "merge_source": "offline_recovery_p1_cached_contacts_v1",
        "p1_remaining_businesses_audited": 64,
        "branch_safe_businesses": 9, "review_businesses": 55,
        "merged_records": sorted(recovery_ids), "before": before, "after": after,
        "net_gain": {key: after[key] - before[key] for key in before},
        "remaining_without_branch_safe_contact_or_staff": 691,
        "organization_shared_values_preserved": len(shared),
        "network_requests": 0, "langsearch_requests": 0, "crm_writes": 0,
        "invariants": {
            "master_is_955": True, "unique_directory_record_ids": True,
            "p1_cohort_conservation_9_safe_plus_55_review": True,
            "shared_emails_not_merged": True, "fax_values_rejected": True,
            "cropo_cardinal_everest_mapping_traps_blocked": True,
            "staff_unchanged": True, "decision_makers_unchanged": True,
            "resolved_plus_unresolved_is_955": True,
        },
    }
    write_json(AUDIT / "summary.json", summary)
    write_json(V9 / "full_955_enrichment.json", output)
    write_json(V9 / "changed_records.json", changed)
    write_json(V9 / "organization_shared_contacts.json", shared)
    write_json(V9 / "summary.json", summary)
    write_json(V9 / "unresolved_after_merge.json", unresolved)
    crm_after = hashlib.sha256(CRM.read_bytes()).hexdigest()
    assert crm_before == crm_after == "c06bee94b72a8bbde83e1755a9897800543f038e255e6e2db72cca744a736b9e"
    print(json.dumps({"summary": summary, "crm_sha256": crm_after}, indent=2))


if __name__ == "__main__":
    main()
