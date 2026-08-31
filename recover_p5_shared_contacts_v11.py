#!/usr/bin/env python3
"""Materialize a conservative first batch from 110 shared-domain P5 records."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from audit_merge_falconer_v7 import metrics, write_json


BASE = Path("data/generated/directory_955")
PAGES = Path("data/generated/batches/4a7aa3af0c4f8a44/pages.json")
SLICE = BASE / "offline_recovery_p5_reconciled_v1/shared_or_other.json"
V10 = BASE / "full_955_enrichment_v10/full_955_enrichment.json"
OUT = BASE / "offline_recovery_p5_shared_contacts_v1"
V11 = BASE / "full_955_enrichment_v11"
CRM = Path("data/crm.sqlite")

RECOVERIES = [
    ("CFI-0063", "https://beaulac.funeraltechweb.com/40/Contact-Us.html", "+13064692277", "Big River\n100 6th Ave. N\nBig River, SK\nS0J0E0\n1-306-469-2277"),
    ("CFI-0064", "https://beaulac.funeraltechweb.com/40/Contact-Us.html", "+13064664822", "Leask\n264 1st Avenue\nLeask, SK\nS0J 1M0\n1-306-466-4822"),
    ("CFI-0065", "https://beaulac.funeraltechweb.com/40/Contact-Us.html", "+13067633322", "Prince Albert\n300B-300\nMarquis Road W\nPrince Albert, SK\nS6V 7L5\nTel:  1-306-763-3322"),
    ("CFI-0066", "https://beaulac.funeraltechweb.com/40/Contact-Us.html", "+13067472828", "Shellbrook\n101 Railway Avenue West\nShellbrook, SK\nS0J2E0\n1-306-747-2828"),
    ("CFI-0252", "https://essentialscbs.com/", "+19053542133", "NIAGARA FALLS\nEssentials Cremation & Burial Services Inc.\n102A-4300 Drummond Road\nNiagara Falls, ON\n​L2E 6C3\nPhone:\n(905) 354-2133"),
    ("CFI-0253", "https://essentialscbs.com/", "+19057341031", "WELLAND\nEssentials Cremation & Burial Services Inc.\n221 Division Street\nWelland, ON\nL3B 4A1\nPhone:\n(905) 734-1031"),
    ("CFI-0448", "https://www.irvinememorial.com/contact-us", "+16133422828", "Irvine Funeral Home and Chapel\n4 James Street East\nBrockville\nON\nK6V 1J9\n613-342-2828"),
    ("CFI-0449", "https://www.irvinememorial.com/contact-us", "+16133483405", "Irvine Memorial Chapel at Roselawn\n2451 County Road 15\nMaitland\nON\nK0E 1P0\n613-348-3405"),
    ("CFI-0496", "https://www.kendrickfuneralhome.com/", "+15197334111", "Kingsville Funeral Home\n519-733-4111\n91 Division Street South\nKingsville, Ontario N9Y 1P5"),
    ("CFI-0497", "https://www.kendrickfuneralhome.com/", "+15193522390", "Chatham Funeral Home\n519-352-2390\n4 Victoria Avenue\nChatham, Ontario N7L 2Z6"),
    ("CFI-0498", "https://www.kendrickfuneralhome.com/", "+15197334111", "Wheatley Funeral Home\n519-7\n33-4111\n17 Little Street South; Box 117\nWheatley, Ontario N0P 2P0"),
    ("CFI-0946", "https://www.wmkippfuneralhome.com/", "+15196328228", "Ayr Chapel, Wm. Kipp Funeral Home\n183 Northumberland Street,\nAyr, ON\nPhone: 519-632-8228"),
    ("CFI-0947", "https://www.wmkippfuneralhome.com/", "+15194423061", "Wm. Kipp Funeral Home Limited\n184 Grand River Street North,\nParis, ON N3L 2N1\nPhone: 519-442-3061"),
]


def main() -> None:
    crm_before = hashlib.sha256(CRM.read_bytes()).hexdigest()
    cohort = json.loads(SLICE.read_text())
    pages = json.loads(PAGES.read_text())
    canonical = json.loads(V10.read_text())
    assert len(cohort) == 110
    cohort_ids = {row["directory_record_id"] for row in cohort}
    by_url = {page["url"]: page for page in pages}
    by_id = {record["directory_record_id"]: record for record in canonical}
    safe = []
    for record_id, url, value, marker in RECOVERIES:
        assert record_id in cohort_ids
        page = by_url[url]
        assert marker in page["text"]
        record = by_id[record_id]
        safe.append({
            "directory_record_id": record_id, "company": record["company"],
            "city": record["city"], "province": record["province"],
            "type": "phone", "value": value, "source_url": url,
            "source_file": str(PAGES),
            "source_text_sha256": hashlib.sha256(page["text"].encode()).hexdigest(),
            "source_html_sha256": hashlib.sha256(page["html"].encode()).hexdigest(),
            "classification": "BRANCH_SAFE",
            "branch_attribution": "Phone is inside an explicit target chapel/location and address block.",
            "evidence_marker": marker,
        })
    safe_ids = {row["directory_record_id"] for row in safe}
    assert len(safe) == 13 and len(safe_ids) == 13
    review = [{
        "directory_record_id": row["directory_record_id"], "company": row["company"],
        "city": row["city"], "classification": "REVIEW",
        "reason": "NOT_IN_FIRST_EXPLICIT_BRANCH_BLOCK_BATCH",
    } for row in cohort if row["directory_record_id"] not in safe_ids]
    assert len(review) == 97 and len(safe) + len(review) == 110
    shared = [
        {"domain": "irvinememorial.com", "type": "email", "value": "info@irvinememorial.com", "reason": "appears in both Brockville and Maitland blocks"},
        {"domain": "kendrickfuneralhome.com", "type": "email", "value": "info@kendrickfuneralhome.com", "reason": "organization footer email"},
        {"domain": "wmkippfuneralhome.com", "type": "email", "value": "wkfh@rogers.com", "reason": "organization footer email; not explicitly isolated to one branch"},
    ]
    write_json(OUT / "branch_safe_contacts.json", safe)
    write_json(OUT / "review_businesses.json", review)
    write_json(OUT / "organization_shared_contacts.json", shared)

    before = metrics(canonical)
    assert before == {
        "businesses_with_email": 158, "businesses_with_phone": 268,
        "businesses_with_staff": 138, "businesses_with_decision_maker": 111,
        "businesses_with_any_safe_contact": 269, "email_values": 270,
        "phone_values": 567, "named_staff": 705, "named_decision_makers": 270,
    }
    output = deepcopy(canonical)
    output_by_id = {record["directory_record_id"]: record for record in output}
    changed = []
    for item in safe:
        record = output_by_id[item["directory_record_id"]]
        enrichment = record["branch_safe_enrichment"]
        assert not enrichment["has_any_contact"]
        phone = {
            "value": item["value"], "source_url": item["source_url"],
            "source_file": item["source_file"], "source_text_sha256": item["source_text_sha256"],
            "source_html_sha256": item["source_html_sha256"],
            "evidence_class": "explicit_branch_contact_block",
            "reason": "phone_inside_target_location_and_address_block",
        }
        enrichment["phones"] = [phone]
        enrichment["has_phone"] = True
        enrichment["has_any_contact"] = True
        enrichment["recovery_provenance"] = [{
            "pipeline": "offline_recovery_p5_shared_contacts_v1",
            "classification": "BRANCH_SAFE", "method": "cached_explicit_location_block",
        }]
        changed.append({
            "directory_record_id": record["directory_record_id"], "company": record["company"],
            "city": record["city"], "province": record["province"],
            "added_emails": [], "added_phones": [phone], "staff_added": [], "decision_makers_added": [],
        })
    after = metrics(output)
    expected_after = dict(before)
    expected_after.update({
        "businesses_with_phone": 281,
        "businesses_with_any_safe_contact": 282,
        "phone_values": 580,
    })
    assert after == expected_after
    unresolved = [record for record in output if not record["branch_safe_enrichment"]["has_any_contact"]]
    assert len(output) == 955 and len({r["directory_record_id"] for r in output}) == 955
    assert len(unresolved) == 673 and 282 + len(unresolved) == 955
    summary = {
        "master_records": 955, "source": "full_955_enrichment_v10",
        "merge_source": "offline_recovery_p5_shared_contacts_v1",
        "shared_slice_businesses": 110, "branch_safe_businesses": 13,
        "remaining_review_businesses": 97, "merged_records": sorted(safe_ids),
        "before": before, "after": after,
        "net_gain": {key: after[key] - before[key] for key in before},
        "remaining_without_branch_safe_contact_or_staff": 673,
        "network_requests": 0, "langsearch_requests": 0, "crm_writes": 0,
        "invariants": {
            "master_is_955": True, "unique_directory_record_ids": True,
            "shared_slice_conservation_13_safe_plus_97_review": True,
            "shared_emails_not_merged": True, "only_explicit_location_blocks_merged": True,
            "staff_unchanged": True, "decision_makers_unchanged": True,
            "resolved_plus_unresolved_is_955": True,
        },
    }
    write_json(OUT / "summary.json", summary)
    write_json(V11 / "full_955_enrichment.json", output)
    write_json(V11 / "changed_records.json", changed)
    write_json(V11 / "organization_shared_contacts.json", shared)
    write_json(V11 / "summary.json", summary)
    write_json(V11 / "unresolved_after_merge.json", unresolved)
    crm_after = hashlib.sha256(CRM.read_bytes()).hexdigest()
    assert crm_before == crm_after == "c06bee94b72a8bbde83e1755a9897800543f038e255e6e2db72cca744a736b9e"
    print(json.dumps({"summary": summary, "crm_sha256": crm_after}, indent=2))


if __name__ == "__main__":
    main()
