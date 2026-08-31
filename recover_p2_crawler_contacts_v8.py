#!/usr/bin/env python3
"""Recover precision-safe contacts from the ten-record P2 crawler cohort."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from audit_merge_falconer_v7 import metrics, write_json


BASE = Path("data/generated/directory_955")
PAGES = Path("data/generated/batches/4a7aa3af0c4f8a44/pages.json")
QUEUE = BASE / "offline_recovery_702_v2/p2_crawler_page.json"
V7 = BASE / "full_955_enrichment_v7/full_955_enrichment.json"
AUDIT = BASE / "offline_recovery_p2_crawler_contacts_v1"
V8 = BASE / "full_955_enrichment_v8"
CRM = Path("data/crm.sqlite")


def main() -> None:
    crm_before = hashlib.sha256(CRM.read_bytes()).hexdigest()
    queue = json.loads(QUEUE.read_text())
    assert len(queue) == 10
    pages = json.loads(PAGES.read_text())
    by_url = {page["url"]: page for page in pages}
    about = by_url["https://interlakecremation.ca/about-us/"]
    contact = by_url["https://interlakecremation.ca/contact/"]
    about_text = about["text"]
    contact_text = contact["text"]
    identity = (
        "Interlake Cremation is owned and operated by Rick Kotaska, a licensed "
        "funeral director and embalmer"
    )
    contact_block = (
        "Box 305, 374 Main Street\nSelkirk, Manitoba\nR1A 2B3\n"
        "Tel: 204-482-1040\nFax: 204-482-8151\nemail:\ninfo@interlakecremation.ca"
    )
    assert identity in about_text and contact_block in contact_text
    contact_sha = hashlib.sha256(contact_text.encode()).hexdigest()
    about_sha = hashlib.sha256(about_text.encode()).hexdigest()
    source_url = "https://interlakecremation.ca/contact/"
    common = {
        "directory_record_id": "CFI-0514",
        "company": "Kotaska Cremation Services",
        "city": "Selkirk",
        "province": "MB",
        "source_url": source_url,
        "source_file": str(PAGES),
        "source_text_sha256": contact_sha,
        "identity_source_url": "https://interlakecremation.ca/about-us/",
        "identity_source_text_sha256": about_sha,
        "classification": "BRANCH_SAFE",
        "branch_attribution": "Contact block explicitly contains the Selkirk address; About page identifies owner Rick Kotaska.",
    }
    email = {**common, "type": "email", "value": "info@interlakecremation.ca"}
    phone = {**common, "type": "phone", "value": "+12044821040"}
    rejected = [{
        **common,
        "type": "phone",
        "value": "+12044828151",
        "classification": "REJECT_FAX",
        "label": "Fax",
    }]
    review = []
    for record in queue:
        record_id = record["directory_record_id"]
        if record_id == "CFI-0514":
            continue
        reason = "NO_CONTACT_VALUES_IN_CACHED_PAGES"
        if record_id in {"CFI-0557", "CFI-0558"}:
            reason = "CONTACT_VALUES_REPEATED_ACROSS_STONEWALL_AND_TEULON"
        elif record_id in {"CFI-0508", "CFI-0855", "CFI-0856"}:
            reason = "GENERIC_DIGNITY_PAGES_WITHOUT_TARGET_BRANCH_IDENTITY"
        elif record_id in {"CFI-0893", "CFI-0894", "CFI-0895"}:
            reason = "CACHED_VOYAGE_PAGES_HAVE_NO_EXTRACTABLE_CONTACT_VALUES"
        review.append({
            "directory_record_id": record_id,
            "company": record["company"],
            "city": record["city"],
            "classification": "REVIEW",
            "reason": reason,
        })
    assert len(review) == 9
    write_json(AUDIT / "branch_safe_contacts.json", [{**common, "emails": [email], "phones": [phone]}])
    write_json(AUDIT / "rejected_contacts.json", rejected)
    write_json(AUDIT / "review_businesses.json", review)

    records = json.loads(V7.read_text())
    before = metrics(records)
    assert before == {
        "businesses_with_email": 157, "businesses_with_phone": 253,
        "businesses_with_staff": 138, "businesses_with_decision_maker": 111,
        "businesses_with_any_safe_contact": 254, "email_values": 269,
        "phone_values": 552, "named_staff": 705, "named_decision_makers": 270,
    }
    output = deepcopy(records)
    target = next(record for record in output if record["directory_record_id"] == "CFI-0514")
    enrichment = target["branch_safe_enrichment"]
    assert not enrichment["has_any_contact"]
    canonical_email = {
        "value": email["value"], "source_url": source_url,
        "source_file": str(PAGES), "source_text_sha256": contact_sha,
        "identity_source_url": common["identity_source_url"],
        "identity_source_text_sha256": about_sha,
        "evidence_class": "explicit_branch_contact_block",
        "reason": "selkirk_address_and_kotaska_owner_identity",
    }
    canonical_phone = {**canonical_email, "value": phone["value"]}
    enrichment["emails"] = [canonical_email]
    enrichment["phones"] = [canonical_phone]
    enrichment["has_email"] = True
    enrichment["has_phone"] = True
    enrichment["has_any_contact"] = True
    enrichment["recovery_provenance"] = [{
        "pipeline": "offline_recovery_p2_crawler_contacts_v1",
        "classification": "BRANCH_SAFE",
        "method": "cached_identity_and_contact_blocks",
    }]
    after = metrics(output)
    assert after == {
        "businesses_with_email": 158, "businesses_with_phone": 254,
        "businesses_with_staff": 138, "businesses_with_decision_maker": 111,
        "businesses_with_any_safe_contact": 255, "email_values": 270,
        "phone_values": 553, "named_staff": 705, "named_decision_makers": 270,
    }
    unresolved = [r for r in output if not r["branch_safe_enrichment"]["has_any_contact"]]
    assert len(output) == 955 and len({r["directory_record_id"] for r in output}) == 955
    assert len(unresolved) == 700 and 255 + len(unresolved) == 955
    changed = [{
        "directory_record_id": "CFI-0514", "company": target["company"],
        "city": target["city"], "province": target["province"],
        "added_emails": [canonical_email], "added_phones": [canonical_phone],
        "staff_added": [], "decision_makers_added": [],
    }]
    summary = {
        "master_records": 955, "source": "full_955_enrichment_v7",
        "merge_source": "offline_recovery_p2_crawler_contacts_v1",
        "p2_businesses_audited": 10, "merged_records": ["CFI-0514"],
        "before": before, "after": after,
        "net_gain": {key: after[key] - before[key] for key in before},
        "remaining_without_branch_safe_contact_or_staff": 700,
        "network_requests": 0, "langsearch_requests": 0, "crm_writes": 0,
        "invariants": {
            "master_is_955": True, "unique_directory_record_ids": True,
            "p2_conservation_1_safe_plus_9_review": True,
            "selkirk_fax_rejected": True, "mackenzie_shared_values_not_merged": True,
            "generic_dignity_contact_not_merged": True,
            "staff_unchanged": True, "decision_makers_unchanged": True,
            "resolved_plus_unresolved_is_955": True,
        },
    }
    write_json(AUDIT / "summary.json", summary)
    write_json(V8 / "full_955_enrichment.json", output)
    write_json(V8 / "changed_records.json", changed)
    write_json(V8 / "summary.json", summary)
    write_json(V8 / "unresolved_after_merge.json", unresolved)
    crm_after = hashlib.sha256(CRM.read_bytes()).hexdigest()
    assert crm_before == crm_after == "c06bee94b72a8bbde83e1755a9897800543f038e255e6e2db72cca744a736b9e"
    print(json.dumps({"summary": summary, "crm_sha256": crm_after}, indent=2))


if __name__ == "__main__":
    main()
