#!/usr/bin/env python3
"""Materialize explicit branch contacts from the final cached P5 review cohort."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from audit_merge_falconer_v7 import metrics, write_json

BASE = Path("data/generated/directory_955")
PAGES = Path("data/generated/batches/4a7aa3af0c4f8a44/pages.json")
REVIEW = BASE / "offline_recovery_p5_shared_contacts_v2/review_businesses.json"
SOURCE = BASE / "full_955_enrichment_v12/full_955_enrichment.json"
AUDIT = BASE / "offline_recovery_p5_shared_contacts_v3"
OUTPUT = BASE / "full_955_enrichment_v13"
CRM = Path("data/crm.sqlite")

RECOVERIES = [
    ("CFI-0905", "https://www.wardfuneralhomes.com/contact-us", "phone", "+19054512124", "Brampton Chapel\n905-451-2124\n1-888-836-6733\n52 Main Street South"),
    ("CFI-0906", "https://www.wardfuneralhomes.com/contact-us", "phone", "+19058519100", "Woodbridge Chapel\n905-851-9100\n1-888-836-6757\n4671 Highway 7"),
    ("CFI-0907", "https://www.wardfuneralhomes.com/contact-us", "phone", "+14162414618", "Weston\n(Toronto) Chapel\n416-241-4618\n1-888-836-6792\n2035 Weston Road"),
    ("CFI-0875", "https://www.tubmanfuneralhomes.com/", "phone", "+16134892033", "1610 Roger Stevens Drive\nKars, ON K0A 2E0\nB.A.O. Licensed FE1 # 311\nTel: (613) 489-2033"),
    ("CFI-0878", "https://www.tubmanfuneralhomes.com/", "phone", "+16138392882", "115 Rivington Street\nCarp, ON K0A 1L0\nB.A.O. Licensed FE1 # 081\nTel:\n(613) 839-2882"),
    ("CFI-0783", "https://serenitynf.funeraltechweb.com/16/Contact-Us.html", "phone", "+17098912225", "95 Main Street, Burin Bay Arm A0E 1G0\nPhone:\n709-891-2225"),
    ("CFI-0783", "https://serenitynf.funeraltechweb.com/16/Contact-Us.html", "email", "serenityfuneralhome@msn.com", "95 Main Street, Burin Bay Arm A0E 1G0\nPhone:\n709-891-2225\n|  Email: serenityfuneralhome@msn.com"),
]


def main() -> None:
    crm_before = hashlib.sha256(CRM.read_bytes()).hexdigest()
    review = json.loads(REVIEW.read_text())
    review_ids = {row["directory_record_id"] for row in review}
    pages = {row["url"]: row for row in json.loads(PAGES.read_text())}
    canonical = json.loads(SOURCE.read_text())
    by_id = {row["directory_record_id"]: row for row in canonical}
    safe = []
    for record_id, url, kind, value, marker in RECOVERIES:
        assert record_id in review_ids
        page = pages[url]
        normalized_text = " ".join(page["text"].split())
        normalized_marker = " ".join(marker.split())
        assert normalized_marker in normalized_text
        record = by_id[record_id]
        safe.append({
            "directory_record_id": record_id, "company": record["company"],
            "city": record["city"], "province": record["province"],
            "type": kind, "value": value, "source_url": url,
            "source_file": str(PAGES),
            "source_text_sha256": hashlib.sha256(page["text"].encode()).hexdigest(),
            "source_html_sha256": hashlib.sha256(page["html"].encode()).hexdigest(),
            "classification": "BRANCH_SAFE", "evidence_marker": marker,
            "branch_attribution": "Contact is inside the target location name/address block.",
        })
    safe_ids = {row["directory_record_id"] for row in safe}
    assert len(safe) == 7 and len(safe_ids) == 6
    remaining = [row for row in review if row["directory_record_id"] not in safe_ids]
    assert len(remaining) == 67 and len(safe_ids) + len(remaining) == 73

    # Adversarial exclusions: placeholders, toll-free alternatives, wrong branch,
    # and a quarantined third-party domain must never become canonical values.
    forbidden = {"+15555555555", "+18888366792", "+18888366793", "+18888366757", "+17098322228"}
    assert not forbidden.intersection({row["value"] for row in safe})
    assert all("usitestat.com" not in row["source_url"] for row in safe)

    write_json(AUDIT / "branch_safe_contacts.json", safe)
    write_json(AUDIT / "review_businesses.json", remaining)
    write_json(AUDIT / "rejected_contacts.json", [
        {"classification": "REJECTED", "values": sorted(forbidden),
         "reason": "placeholder, toll-free alternative, or wrong-branch phone"},
        {"classification": "REJECTED", "domain": "tubmanfuneralhomes.com.usitestat.com",
         "reason": "quarantined third-party mirror"},
    ])

    before = metrics(canonical)
    assert before == {
        "businesses_with_email": 158, "businesses_with_phone": 305,
        "businesses_with_staff": 138, "businesses_with_decision_maker": 111,
        "businesses_with_any_safe_contact": 306, "email_values": 270,
        "phone_values": 604, "named_staff": 705, "named_decision_makers": 270,
    }
    output = deepcopy(canonical)
    out_by_id = {row["directory_record_id"]: row for row in output}
    changed = []
    for record_id in sorted(safe_ids):
        items = [row for row in safe if row["directory_record_id"] == record_id]
        record = out_by_id[record_id]
        enrichment = record["branch_safe_enrichment"]
        assert not enrichment["has_any_contact"]
        added_emails, added_phones = [], []
        for item in items:
            value = {
                "value": item["value"], "source_url": item["source_url"],
                "source_file": item["source_file"],
                "source_text_sha256": item["source_text_sha256"],
                "source_html_sha256": item["source_html_sha256"],
                "evidence_class": "explicit_branch_contact_block",
                "reason": f"{item['type']}_inside_target_location_and_address_block",
            }
            enrichment[f"{item['type']}s"].append(value)
            enrichment[f"has_{item['type']}"] = True
            (added_emails if item["type"] == "email" else added_phones).append(value)
        enrichment["has_any_contact"] = True
        enrichment["recovery_provenance"] = [{
            "pipeline": "offline_recovery_p5_shared_contacts_v3",
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
        "businesses_with_email": 159, "businesses_with_phone": 311,
        "businesses_with_any_safe_contact": 312, "email_values": 271,
        "phone_values": 610,
    })
    assert after == expected
    unresolved = [row for row in output if not row["branch_safe_enrichment"]["has_any_contact"]]
    assert len(output) == 955 and len({row["directory_record_id"] for row in output}) == 955
    assert len(unresolved) == 643 and 312 + len(unresolved) == 955
    summary = {
        "master_records": 955, "source": "full_955_enrichment_v12",
        "merge_source": "offline_recovery_p5_shared_contacts_v3",
        "input_review_businesses": 73, "branch_safe_businesses": 6,
        "branch_safe_values": 7, "remaining_review_businesses": 67,
        "merged_records": sorted(safe_ids), "before": before, "after": after,
        "net_gain": {key: after[key] - before[key] for key in before},
        "remaining_without_branch_safe_contact_or_staff": 643,
        "network_requests": 0, "langsearch_requests": 0, "crm_writes": 0,
        "invariants": {
            "master_is_955": True, "unique_directory_record_ids": True,
            "review_conservation_6_safe_plus_67_review": True,
            "only_explicit_location_blocks_merged": True,
            "adversarial_values_rejected": True, "staff_unchanged": True,
            "decision_makers_unchanged": True, "resolved_plus_unresolved_is_955": True,
        },
    }
    write_json(AUDIT / "summary.json", summary)
    write_json(OUTPUT / "full_955_enrichment.json", output)
    write_json(OUTPUT / "changed_records.json", changed)
    write_json(OUTPUT / "organization_shared_contacts.json", [])
    write_json(OUTPUT / "summary.json", summary)
    write_json(OUTPUT / "unresolved_after_merge.json", unresolved)
    crm_after = hashlib.sha256(CRM.read_bytes()).hexdigest()
    assert crm_before == crm_after == "c06bee94b72a8bbde83e1755a9897800543f038e255e6e2db72cca744a736b9e"
    print(json.dumps({"summary": summary, "crm_sha256": crm_after}, indent=2))


if __name__ == "__main__":
    main()
