#!/usr/bin/env python3
"""Attribute P4 crawl evidence and materialize five branch-safe phones into V10."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from audit_merge_falconer_v7 import metrics, write_json


BASE = Path("data/generated/directory_955")
QUEUE = BASE / "offline_recovery_702_v2/p4_known_domain.json"
BATCH = Path("data/generated/batches/6666a0ec1ad89869")
V9 = BASE / "full_955_enrichment_v9/full_955_enrichment.json"
AUDIT = BASE / "offline_recovery_p4_known_domain_v1"
V10 = BASE / "full_955_enrichment_v10"
CRM = Path("data/crm.sqlite")

RECOVERIES = [
    ("CFI-0743", "https://www.redpathfuneralhome.com/contact-us", "+12045223361", "Redpath Funeral Home - Melita Location\n21 Main Street North P.O. Box 970\nMelita, MB R0M 1L0\n1-204-522-3361"),
    ("CFI-0756", "https://www.ronaldmoffitmemorialservices.com/contact-us", "+12048563487", "306 Saskatchewan Avenue East\n|\nPortage la Prairie\n,\nMB\nR1N 0K8\n|\nTel:\n1-204-856-3487"),
    ("CFI-0929", "https://www.whitesfh.ca/contact-us", "+12048342629", "White's Funeral Home - Carberry\n|\n143 Ottawa Street\n|\nCarberry\n,\nMB\nR0K 0H0\n|\nTel:\n1-204-834-2629"),
    ("CFI-0930", "https://www.whitesfh.ca/contact-us", "+12044762848", "White's Funeral Home - Neepawa\n|\n271 Mountain Avenue / PO Box 326\n|\nNeepawa\n,\nMB\nR0J 1H0\n|\nTel:\n1-204-476-2848"),
    ("CFI-0931", "https://www.whitesfh.ca/contact-us", "+12048673868", "White's Funeral Home - Minnedosa\n|\nBox 1620\n|\nMinnedosa\n,\nMB\nR0J 1E0\n|\nTel:\n204-867-3868"),
]


def main() -> None:
    crm_before = hashlib.sha256(CRM.read_bytes()).hexdigest()
    queue = json.loads(QUEUE.read_text())
    pages = json.loads((BATCH / "pages.json").read_text())
    report = json.loads((BATCH / "crawl_report.json").read_text())
    canonical = json.loads(V9.read_text())
    assert len(queue) == 45 and report["queued_domains"] == 32
    assert report["successful_domains"] == 5 and len(report["failed_domains"]) == 27
    assert sum(report["attempt_outcomes"].values()) == 274
    assert report["attempt_outcomes"]["CROSS_DOMAIN_REDIRECT"] == 4
    by_url = {page["url"]: page for page in pages}
    by_id = {record["directory_record_id"]: record for record in canonical}
    safe = []
    for record_id, url, value, marker in RECOVERIES:
        page = by_url[url]
        assert marker in page["text"]
        record = by_id[record_id]
        safe.append({
            "directory_record_id": record_id, "company": record["company"],
            "city": record["city"], "province": record["province"],
            "type": "phone", "value": value, "source_url": url,
            "source_file": str(BATCH / "pages.json"),
            "source_text_sha256": hashlib.sha256(page["text"].encode()).hexdigest(),
            "source_html_sha256": hashlib.sha256(page["html"].encode()).hexdigest(),
            "classification": "BRANCH_SAFE",
            "branch_attribution": "Phone is inside the explicit target branch name/address block.",
            "evidence_marker": marker,
        })
    safe_ids = {item["directory_record_id"] for item in safe}
    domain_status = {row["domain"]: row for row in report["leads"]}
    review = []
    for row in queue:
        record_id = row["directory_record_id"]
        if record_id in safe_ids:
            continue
        domain = row["domains"][0]
        status = domain_status[domain]
        reason = f"NO_BRANCH_SAFE_PAGE:{status['status']}:{status.get('reason', 'NO_CONTACT_BLOCK')}"
        if record_id in {"CFI-0466", "CFI-0467"}:
            reason = "WILLMOR_PHONES_NOT_MAPPED_TO_HOLLAND_VERSUS_GLENBORO_BLOCKS"
        elif record_id == "CFI-0651":
            reason = "WRONG_BRANCH:CRAWLED_WOLKOWSKI_PAGE_IS_KAMSACK_NOT_ROBLIN"
        review.append({
            "directory_record_id": record_id, "company": row["company"],
            "city": row["city"], "domain": domain,
            "classification": "REVIEW", "reason": reason,
        })
    assert len(safe) == 5 and len(review) == 40 and len(safe) + len(review) == 45
    rejected = [
        {"value": "+12045223135", "classification": "REJECT_FAX", "paired_branch": "Melita"},
        {"value": "+12042390233", "classification": "REJECT_FAX", "paired_branch": "Portage la Prairie"},
        {"value": "+13065423378", "classification": "REJECT_FAX", "paired_branch": "Kamsack (wrong branch)"},
    ]
    write_json(AUDIT / "branch_safe_contacts.json", safe)
    write_json(AUDIT / "review_businesses.json", review)
    write_json(AUDIT / "rejected_contacts.json", rejected)

    before = metrics(canonical)
    assert before == {
        "businesses_with_email": 158, "businesses_with_phone": 263,
        "businesses_with_staff": 138, "businesses_with_decision_maker": 111,
        "businesses_with_any_safe_contact": 264, "email_values": 270,
        "phone_values": 562, "named_staff": 705, "named_decision_makers": 270,
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
            "reason": "phone_inside_target_branch_name_and_address_block",
        }
        enrichment["phones"] = [phone]
        enrichment["has_phone"] = True
        enrichment["has_any_contact"] = True
        enrichment["recovery_provenance"] = [{
            "pipeline": "offline_recovery_p4_known_domain_v1",
            "classification": "BRANCH_SAFE", "method": "isolated_crawl_branch_block",
        }]
        changed.append({
            "directory_record_id": record["directory_record_id"], "company": record["company"],
            "city": record["city"], "province": record["province"],
            "added_emails": [], "added_phones": [phone], "staff_added": [], "decision_makers_added": [],
        })
    after = metrics(output)
    expected_after = dict(before)
    expected_after.update({
        "businesses_with_phone": 268,
        "businesses_with_any_safe_contact": 269,
        "phone_values": 567,
    })
    assert after == expected_after
    unresolved = [record for record in output if not record["branch_safe_enrichment"]["has_any_contact"]]
    assert len(output) == 955 and len({r["directory_record_id"] for r in output}) == 955
    assert len(unresolved) == 686 and 269 + len(unresolved) == 955
    summary = {
        "master_records": 955, "source": "full_955_enrichment_v9",
        "merge_source": "offline_recovery_p4_known_domain_v1",
        "p4_businesses": 45, "unique_domains": 32,
        "successful_domains": 5, "failed_domains": 27,
        "crawl_attempts": 274, "crawl_pages_reported": report["pages"],
        "branch_safe_businesses": 5, "review_businesses": 40,
        "merged_records": sorted(safe_ids), "before": before, "after": after,
        "net_gain": {key: after[key] - before[key] for key in before},
        "remaining_without_branch_safe_contact_or_staff": 686,
        "langsearch_requests": 0, "crm_writes": 0,
        "invariants": {
            "master_is_955": True, "unique_directory_record_ids": True,
            "p4_conservation_5_safe_plus_40_review": True,
            "cross_domain_redirects_failed_closed": True,
            "willmor_ambiguous_mapping_blocked": True,
            "wolkowski_wrong_branch_blocked": True, "fax_values_rejected": True,
            "staff_unchanged": True, "decision_makers_unchanged": True,
            "resolved_plus_unresolved_is_955": True,
        },
    }
    write_json(AUDIT / "summary.json", summary)
    write_json(V10 / "full_955_enrichment.json", output)
    write_json(V10 / "changed_records.json", changed)
    write_json(V10 / "summary.json", summary)
    write_json(V10 / "unresolved_after_merge.json", unresolved)
    crm_after = hashlib.sha256(CRM.read_bytes()).hexdigest()
    assert crm_before == crm_after == "c06bee94b72a8bbde83e1755a9897800543f038e255e6e2db72cca744a736b9e"
    print(json.dumps({"summary": summary, "crm_sha256": crm_after}, indent=2))


if __name__ == "__main__":
    main()
