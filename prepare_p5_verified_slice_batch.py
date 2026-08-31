#!/usr/bin/env python3
"""Reconcile stale P5 categories and prepare its clean verified-site slice."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


BASE = Path("data/generated/directory_955")
P5 = BASE / "offline_recovery_702_v2/p5_no_local_web_evidence.json"
OLD = BASE / "offline_recovery_709_v1"
MAPPINGS = BASE / "verified_crawlset/business_website_mappings.json"
V10 = BASE / "full_955_enrichment_v10/full_955_enrichment.json"
OUT = BASE / "offline_recovery_p5_reconciled_v1"
CRM = Path("data/crm.sqlite")
EXCLUDED = {
    "CFI-0567": "THIRD_PARTY_MAHONE_BAY_DIRECTORY",
    "CFI-0634": "WRONG_BUSINESS_GORDON_MONK_DOMAIN_FOR_MORGAN",
    "CFI-0690": "GENERIC_GATEWAY_OBITUARY_HOST_WITHOUT_ORAM_IDENTITY",
}


def load_rows(path: Path) -> list[dict]:
    value = json.loads(path.read_text())
    return value if isinstance(value, list) else next(v for v in value.values() if isinstance(v, list))


def main() -> None:
    crm_before = hashlib.sha256(CRM.read_bytes()).hexdigest()
    p5 = load_rows(P5)
    p5_ids = {row["directory_record_id"] for row in p5}
    categories = {
        "verified_no_contact": load_rows(OLD / "p4_verified_website_no_safe_contact.json"),
        "no_verified_website": load_rows(OLD / "p5_no_verified_website.json"),
        "quarantined_website": load_rows(OLD / "p6_quarantined_website.json"),
        "shared_or_other": load_rows(OLD / "p7_other.json"),
    }
    reconciled = {
        name: [row for row in rows if row["directory_record_id"] in p5_ids]
        for name, rows in categories.items()
    }
    counts = {name: len(rows) for name, rows in reconciled.items()}
    assert len(p5) == 569
    assert counts == {
        "verified_no_contact": 32,
        "no_verified_website": 409,
        "quarantined_website": 18,
        "shared_or_other": 110,
    }
    assert sum(counts.values()) == 569
    assert len({row["directory_record_id"] for rows in reconciled.values() for row in rows}) == 569
    mappings = {row["directory_record_id"]: row for row in load_rows(MAPPINGS)}
    canonical = {row["directory_record_id"]: row for row in load_rows(V10)}
    verified = reconciled["verified_no_contact"]
    assert all(not canonical[row["directory_record_id"]]["branch_safe_enrichment"]["has_any_contact"] for row in verified)
    source = []
    exclusions = []
    for row in verified:
        record_id = row["directory_record_id"]
        mapping = mappings[record_id]
        if record_id in EXCLUDED:
            exclusions.append({**row, "website": mapping["website"], "reason": EXCLUDED[record_id]})
            continue
        source.append({
            "directory_record_id": record_id,
            "company": row["company"], "city": row["city"], "province": row["province"],
            "country": "Canada", "website": f"https://{mapping['domain']}/",
            "source_url": mapping["website"], "category": "funeral_home",
        })
    assert len(source) == 29 and len(exclusions) == 3
    OUT.mkdir(parents=True, exist_ok=True)
    for name, rows in reconciled.items():
        (OUT / f"{name}.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n")
    source_path = OUT / "verified_slice_crawler_source.json"
    source_path.write_text(json.dumps(source, indent=2, ensure_ascii=False) + "\n")
    (OUT / "excluded_wrong_or_third_party.json").write_text(json.dumps(exclusions, indent=2, ensure_ascii=False) + "\n")
    summary = {
        "input_p5_businesses": 569,
        "reconciled_counts": counts,
        "verified_slice_businesses": 32,
        "crawler_source_businesses": 29,
        "excluded_wrong_or_third_party": 3,
        "network_requests": 0, "langsearch_requests": 0, "crm_writes": 0,
        "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "invariants": {
            "p5_conservation": True, "category_ids_unique": True,
            "all_verified_targets_unresolved_in_v10": True,
            "known_wrong_and_third_party_mappings_excluded": True,
        },
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    crm_after = hashlib.sha256(CRM.read_bytes()).hexdigest()
    assert crm_before == crm_after == "c06bee94b72a8bbde83e1755a9897800543f038e255e6e2db72cca744a736b9e"
    print(json.dumps({"source": str(source_path), "summary": summary, "crm_sha256": crm_after}, indent=2))


if __name__ == "__main__":
    main()
