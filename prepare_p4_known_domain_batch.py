#!/usr/bin/env python3
"""Prepare a deterministic crawler source for the 45-record P4 cohort."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


BASE = Path("data/generated/directory_955")
QUEUE = BASE / "offline_recovery_702_v2/p4_known_domain.json"
V9 = BASE / "full_955_enrichment_v9/full_955_enrichment.json"
OUT = BASE / "offline_recovery_p4_known_domain_v1"
CRM = Path("data/crm.sqlite")


def main() -> None:
    crm_before = hashlib.sha256(CRM.read_bytes()).hexdigest()
    queue = json.loads(QUEUE.read_text())
    canonical = json.loads(V9.read_text())
    by_id = {row["directory_record_id"]: row for row in canonical}
    assert len(queue) == 45
    assert len({row["directory_record_id"] for row in queue}) == 45
    assert all(len(row["domains"]) == 1 for row in queue)
    assert all(not by_id[row["directory_record_id"]]["branch_safe_enrichment"]["has_any_contact"] for row in queue)
    source = [
        {
            "directory_record_id": row["directory_record_id"],
            "company": row["company"],
            "city": row["city"],
            "province": row["province"],
            "country": "Canada",
            "website": f"https://{row['domains'][0]}/",
            "source_url": str(QUEUE),
            "category": "funeral_home",
        }
        for row in queue
    ]
    OUT.mkdir(parents=True, exist_ok=True)
    source_path = OUT / "crawler_source.json"
    source_path.write_text(json.dumps(source, indent=2, ensure_ascii=False) + "\n")
    summary = {
        "input_businesses": 45,
        "unique_domains": len({row["domains"][0] for row in queue}),
        "canonical_source": "full_955_enrichment_v9",
        "network_requests": 0,
        "langsearch_requests": 0,
        "crm_writes": 0,
        "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "invariants": {
            "p4_is_45": True,
            "all_targets_unresolved_in_v9": True,
            "one_verified_domain_per_target": True,
            "https_roots_only": True,
        },
    }
    (OUT / "prepare_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    crm_after = hashlib.sha256(CRM.read_bytes()).hexdigest()
    assert crm_before == crm_after == "c06bee94b72a8bbde83e1755a9897800543f038e255e6e2db72cca744a736b9e"
    print(json.dumps({"source": str(source_path), "summary": summary, "crm_sha256": crm_after}, indent=2))


if __name__ == "__main__":
    main()
