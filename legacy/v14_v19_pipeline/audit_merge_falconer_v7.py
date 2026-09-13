#!/usr/bin/env python3
"""Audit cached Falconer branch blocks and materialize the precision-safe V7."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path


BASE = Path("data/generated/directory_955")
EVIDENCE = BASE / "targeted_recovery_fetch_v1/page_evidence.json"
V6 = BASE / "full_955_enrichment_v6/full_955_enrichment.json"
AUDIT_DIR = BASE / "offline_recovery_falconer_final_audit_v1"
V7_DIR = BASE / "full_955_enrichment_v7"
CRM = Path("data/crm.sqlite")
SOURCE_URL = "https://www.falconerfuneralhomes.com/contact-us"
SOURCE_SHA256 = "9f5809beea08279d17b2072590161f09f92d877df3e1fb9680ec63e87f88ec63"
CLINTON_PHONE = "+15194829521"
SHARED_EMAIL = "info@falconerfuneralhomes.com"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def metrics(records: list[dict]) -> dict[str, int]:
    enrichments = [record["branch_safe_enrichment"] for record in records]
    return {
        "businesses_with_email": sum(bool(item["emails"]) for item in enrichments),
        "businesses_with_phone": sum(bool(item["phones"]) for item in enrichments),
        "businesses_with_staff": sum(bool(item["staff"]) for item in enrichments),
        "businesses_with_decision_maker": sum(bool(item["decision_makers"]) for item in enrichments),
        "businesses_with_any_safe_contact": sum(
            bool(item["emails"] or item["phones"] or item["staff"]) for item in enrichments
        ),
        "email_values": sum(len(item["emails"]) for item in enrichments),
        "phone_values": sum(len(item["phones"]) for item in enrichments),
        "named_staff": sum(len(item["staff"]) for item in enrichments),
        "named_decision_makers": sum(len(item["decision_makers"]) for item in enrichments),
    }


def main() -> None:
    crm_before = hashlib.sha256(CRM.read_bytes()).hexdigest()
    evidence = json.loads(EVIDENCE.read_text())
    pages = [
        page for page in evidence
        if page["directory_record_id"] in {"CFI-0268", "CFI-0269"}
        and page["url"] == SOURCE_URL
    ]
    assert len(pages) == 2
    assert {page["text_sha256"] for page in pages} == {SOURCE_SHA256}
    text = pages[0]["text"]

    clinton_block = (
        "519 482-9521 Clinton Chapel 153 High Street - P. O. Box 249 Clinton, "
        "Ontario NOM 1L0 Fax: 519 482-9441 info@falconerfuneralhomes.com"
    )
    goderich_block = (
        "519 524-1221 Bluewater Chapel 201 Suncoast Drive, East Goderich, "
        "Ontario N7A 4H8 Fax: 519 524-5875 info@falconerfuneralhomes.com"
    )
    assert clinton_block in text
    assert goderich_block in text
    assert text.count(SHARED_EMAIL) == 4
    assert text.count("519-482-9521") == 1 and text.count("519 482-9521") == 1

    phone = {
        "directory_record_id": "CFI-0269",
        "company": "Falconer Funeral Homes",
        "city": "Clinton",
        "province": "ON",
        "type": "phone",
        "value": CLINTON_PHONE,
        "source_url": SOURCE_URL,
        "source_file": str(EVIDENCE),
        "source_text_sha256": SOURCE_SHA256,
        "classification": "BRANCH_SAFE",
        "branch_attribution": "Phone immediately precedes the Clinton Chapel heading and address.",
    }
    shared = {
        "organization_record_ids": ["CFI-0268", "CFI-0269"],
        "company": "Falconer Funeral Homes",
        "type": "email",
        "value": SHARED_EMAIL,
        "source_url": SOURCE_URL,
        "source_file": str(EVIDENCE),
        "source_text_sha256": SOURCE_SHA256,
        "classification": "ORGANIZATION_SHARED",
        "branch_attribution": "The identical email is repeated inside both Clinton and Goderich branch blocks.",
    }
    rejected = [
        {
            "value": "+15194829441",
            "type": "phone",
            "classification": "REJECT_FAX",
            "paired_branch": "Clinton",
            "label": "Fax",
        },
        {
            "value": "+15195241221",
            "type": "phone",
            "classification": "WRONG_BRANCH",
            "paired_branch": "Goderich",
            "label": "Bluewater Chapel",
        },
        {
            "value": "+15195245875",
            "type": "phone",
            "classification": "REJECT_FAX",
            "paired_branch": "Goderich",
            "label": "Fax",
        },
    ]
    block_audit = {
        "source_url": SOURCE_URL,
        "source_file": str(EVIDENCE),
        "source_text_sha256": SOURCE_SHA256,
        "network_requests": 0,
        "blocks": [
            {
                "branch": "Clinton Chapel",
                "address": "153 High Street, P.O. Box 249, Clinton, ON N0M 1L0",
                "phone": CLINTON_PHONE,
                "fax": "+15194829441",
                "email": SHARED_EMAIL,
                "exact_cached_text": clinton_block,
            },
            {
                "branch": "Bluewater Chapel",
                "address": "201 Suncoast Drive East, Goderich, ON N7A 4H8",
                "phone": "+15195241221",
                "fax": "+15195245875",
                "email": SHARED_EMAIL,
                "exact_cached_text": goderich_block,
            },
        ],
        "conclusion": "Clinton phone is branch-safe; repeated email is organization-shared.",
    }
    audit_summary = {
        "audited_businesses": 1,
        "branch_safe_values": 1,
        "organization_shared_values": 1,
        "rejected_values": 3,
        "network_requests": 0,
        "langsearch_requests": 0,
        "crm_writes": 0,
        "merged_records": 0,
        "invariants": {
            "cached_body_sha256_matches": True,
            "clinton_phone_explicitly_paired": True,
            "email_repeated_for_both_branches": True,
            "fax_values_rejected": True,
            "goderich_phone_not_assigned_to_clinton": True,
        },
    }
    write_json(AUDIT_DIR / "contact_block_audit.json", block_audit)
    write_json(AUDIT_DIR / "branch_safe_contacts.json", [phone])
    write_json(AUDIT_DIR / "organization_shared_contacts.json", [shared])
    write_json(AUDIT_DIR / "rejected_contacts.json", rejected)
    write_json(AUDIT_DIR / "summary.json", audit_summary)

    records = json.loads(V6.read_text())
    before = metrics(records)
    expected_before = {
        "businesses_with_email": 157, "businesses_with_phone": 252,
        "businesses_with_staff": 138, "businesses_with_decision_maker": 111,
        "businesses_with_any_safe_contact": 253, "email_values": 269,
        "phone_values": 551, "named_staff": 705, "named_decision_makers": 270,
    }
    assert len(records) == 955 and before == expected_before
    assert len({record["directory_record_id"] for record in records}) == 955
    output = deepcopy(records)
    target = next(record for record in output if record["directory_record_id"] == "CFI-0269")
    enrichment = target["branch_safe_enrichment"]
    assert not enrichment["emails"] and not enrichment["phones"] and not enrichment["staff"]
    canonical_phone = {key: phone[key] for key in ("value", "source_url")}
    canonical_phone.update({
        "source_file": phone["source_file"],
        "source_text_sha256": phone["source_text_sha256"],
        "evidence_class": "explicit_branch_contact_block",
        "reason": "phone_immediately_precedes_clinton_chapel_heading_and_address",
    })
    enrichment["phones"] = [canonical_phone]
    enrichment["has_phone"] = True
    enrichment["has_any_contact"] = True
    enrichment["recovery_provenance"] = [{
        "pipeline": "offline_recovery_falconer_final_audit_v1",
        "classification": "BRANCH_SAFE",
        "method": "cached_branch_contact_block",
    }]
    after = metrics(output)
    expected_after = dict(expected_before)
    expected_after.update({
        "businesses_with_phone": 253,
        "businesses_with_any_safe_contact": 254,
        "phone_values": 552,
    })
    assert after == expected_after
    unresolved = [
        record for record in output
        if not record["branch_safe_enrichment"]["has_any_contact"]
    ]
    assert len(unresolved) == 701 and 254 + len(unresolved) == 955
    assert not enrichment["emails"]

    changed = [{
        "directory_record_id": "CFI-0269",
        "company": target["company"],
        "city": target["city"],
        "province": target["province"],
        "added_emails": [],
        "added_phones": [canonical_phone],
        "staff_added": [],
        "decision_makers_added": [],
    }]
    summary = {
        "master_records": 955,
        "source": "full_955_enrichment_v6",
        "merge_source": "offline_recovery_falconer_final_audit_v1",
        "merged_records": ["CFI-0269"],
        "before": before,
        "after": after,
        "net_gain": {key: after[key] - before[key] for key in before},
        "remaining_without_branch_safe_contact_or_staff": len(unresolved),
        "organization_shared_contacts_preserved": 1,
        "crm_writes": 0,
        "invariants": {
            "master_is_955": True,
            "unique_directory_record_ids": True,
            "source_baseline_exact": True,
            "phone_only_merge": True,
            "falconer_email_not_merged": True,
            "staff_unchanged": True,
            "decision_makers_unchanged": True,
            "resolved_plus_unresolved_is_955": True,
        },
    }
    write_json(V7_DIR / "full_955_enrichment.json", output)
    write_json(V7_DIR / "changed_records.json", changed)
    write_json(V7_DIR / "organization_shared_contacts.json", [shared])
    write_json(V7_DIR / "summary.json", summary)
    write_json(V7_DIR / "unresolved_after_merge.json", unresolved)
    crm_after = hashlib.sha256(CRM.read_bytes()).hexdigest()
    assert crm_before == crm_after == "c06bee94b72a8bbde83e1755a9897800543f038e255e6e2db72cca744a736b9e"
    print(json.dumps({"audit": audit_summary, "v7": summary, "crm_sha256": crm_after}, indent=2))


if __name__ == "__main__":
    main()
