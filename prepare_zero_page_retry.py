#!/usr/bin/env python3
"""Build the deterministic recovery queue for verified zero-page domains."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


BASE = Path("data/generated/directory_955")
QUEUE = BASE / "verified_crawlset/crawl_queue.json"
REPORT = Path("data/generated/batches/4a7aa3af0c4f8a44/crawl_report.json")
OUT = BASE / "zero_page_retry_v1"
CRM = Path("data/crm.sqlite")
CRM_SHA256 = "c06bee94b72a8bbde83e1755a9897800543f038e255e6e2db72cca744a736b9e"


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def main() -> None:
    crm_before = hashlib.sha256(CRM.read_bytes()).hexdigest()
    queue = json.loads(QUEUE.read_text())
    report = json.loads(REPORT.read_text())
    failed = set(report["failed_domains"])
    selected = [row for row in queue if row["domain"] in failed]
    selected.sort(key=lambda row: row["domain"])
    selected_domains = {row["domain"] for row in selected}
    business_ids = {
        record_id for row in selected for record_id in row.get("directory_record_ids") or []
    }
    assert len(queue) == 352
    assert len(failed) == 38
    assert selected_domains == failed
    assert len(selected) == 38
    assert len(business_ids) == 50
    assert sum(int(row.get("business_count") or 0) for row in selected) == 50
    write_json(OUT / "crawl_queue.json", selected)
    write_json(OUT / "prepare_summary.json", {
        "source_domains": 352,
        "zero_page_domains": 38,
        "mapped_businesses": 50,
        "queue_domains": len(selected),
        "queue_businesses": len(business_ids),
        "source_queue": str(QUEUE),
        "source_report": str(REPORT),
        "network_requests": 0,
        "crm_writes": 0,
        "invariants": {
            "failed_domains_exactly_match_queue": True,
            "domain_conservation": True,
            "business_conservation": True,
        },
    })
    crm_after = hashlib.sha256(CRM.read_bytes()).hexdigest()
    assert crm_before == crm_after == CRM_SHA256
    print(json.dumps({"domains": len(selected), "businesses": len(business_ids),
                      "crm_sha256": crm_after}, indent=2))


if __name__ == "__main__":
    main()
