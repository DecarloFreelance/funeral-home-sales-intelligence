#!/usr/bin/env python3
"""Fail-closed audit of the three-record P3 cached-search cohort."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from audit_merge_falconer_v7 import write_json


BASE = Path("data/generated/directory_955")
QUEUE = BASE / "offline_recovery_702_v2/p3_cached_search.json"
SEARCH = BASE / "targeted_recovery_search/search_results.json"
V9 = BASE / "full_955_enrichment_v9/full_955_enrichment.json"
OUT = BASE / "offline_recovery_p3_cached_search_audit_v1"
CRM = Path("data/crm.sqlite")


def main() -> None:
    crm_before = hashlib.sha256(CRM.read_bytes()).hexdigest()
    queue = json.loads(QUEUE.read_text())
    assert len(queue) == 3
    ids = {row["directory_record_id"] for row in queue}
    results = [row for row in json.loads(SEARCH.read_text()) if row["directory_record_id"] in ids]
    assert len(results) == 3 and all(row["status"] == "OK" for row in results)
    by_id = {row["directory_record_id"]: row for row in results}
    assert by_id["CFI-0299"]["result_count"] == 8
    assert {item["domain"] for item in by_id["CFI-0299"]["results"]} == {"dignitymemorial.com"}
    assert by_id["CFI-0342"]["result_count"] == 1
    assert by_id["CFI-0342"]["results"][0]["url"] == "https://amgfh.com/"
    assert by_id["CFI-0403"]["result_count"] == 4
    assert all("/book-of-memories/" in item["url"] for item in by_id["CFI-0403"]["results"])

    classifications = [
        {
            "directory_record_id": "CFI-0299",
            "company": "Fletcher Funeral Chapel and Cremation Services",
            "city": "Radville",
            "classification": "UNRESOLVED",
            "reason": "All cached results are generic or unrelated Dignity pages with no Fletcher/Radville branch identity.",
        },
        {
            "directory_record_id": "CFI-0342",
            "company": "George Funeral Home Ltd.",
            "city": "Wiarton",
            "classification": "WRONG_BUSINESS",
            "reason": "Only result is A. Millard George Funeral Home in London, not George Funeral Home in Wiarton.",
        },
        {
            "directory_record_id": "CFI-0403",
            "company": "Hendren Funeral Home Ltd. (1987)",
            "city": "Lakefield",
            "classification": "REJECT_WEAK_SOURCE",
            "reason": "All cached results are legacy obituary/service pages; no current official branch contact page is present.",
        },
    ]
    canonical = json.loads(V9.read_text())
    canonical_by_id = {row["directory_record_id"]: row for row in canonical}
    assert all(not canonical_by_id[item["directory_record_id"]]["branch_safe_enrichment"]["has_any_contact"] for item in classifications)
    summary = {
        "input_businesses": 3,
        "cached_search_results": sum(row["result_count"] for row in results),
        "branch_safe_businesses": 0,
        "unresolved_businesses": 3,
        "network_requests": 0,
        "langsearch_requests": 0,
        "crm_writes": 0,
        "merged_records": 0,
        "canonical_source": "full_955_enrichment_v9",
        "canonical_records": len(canonical),
        "invariants": {
            "p3_is_3": True,
            "all_cached_results_conserved": True,
            "wrong_george_business_blocked": True,
            "hendren_obituary_pages_blocked": True,
            "generic_dignity_results_blocked": True,
            "nothing_merged": True,
        },
    }
    write_json(OUT / "classifications.json", classifications)
    write_json(OUT / "summary.json", summary)
    crm_after = hashlib.sha256(CRM.read_bytes()).hexdigest()
    assert crm_before == crm_after == "c06bee94b72a8bbde83e1755a9897800543f038e255e6e2db72cca744a736b9e"
    print(json.dumps({"summary": summary, "crm_sha256": crm_after}, indent=2))


if __name__ == "__main__":
    main()
