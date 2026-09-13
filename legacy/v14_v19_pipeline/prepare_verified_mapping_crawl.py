#!/usr/bin/env python3
"""Prepare a domain-deduplicated bounded crawl from fresh verification rows."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from audit_merge_falconer_v7 import write_json
from verify_langsearch_recovery_v2 import enforce_first_party

PATHS = (
    "/contact", "/contact-us", "/about", "/about-us", "/staff", "/team",
    "/our-team", "/meet-the-team", "/directors", "/funeral-directors", "/locations",
)


def prepare(verification_path: Path, output: Path) -> dict:
    rows = json.loads(verification_path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("Verification rows must be a JSON list")
    verified = []
    seen: set[str] = set()
    by_domain: dict[str, list[dict]] = defaultdict(list)
    for raw in rows:
        row = enforce_first_party(raw)
        record_id = str(row.get("directory_record_id") or "")
        if not record_id or record_id in seen:
            raise ValueError(f"Missing or duplicate directory_record_id: {record_id!r}")
        seen.add(record_id)
        if row.get("status") not in {"VERIFIED", "VERIFIED_HIGH"}:
            continue
        parts = urlsplit(str(row.get("website") or ""))
        domain = (parts.hostname or "").casefold().removeprefix("www.")
        if parts.scheme not in {"http", "https"} or not domain or parts.username or parts.password:
            raise ValueError(f"Unsafe verified website for {record_id}")
        item = {
            "directory_record_id": record_id,
            "company": row.get("company"), "city": row.get("city"),
            "province": row.get("province"), "website": row.get("website"),
            "domain": domain, "verification_class": row.get("status"),
            "verification_score": row.get("verification_score"),
            "source": "legacy_mapping_current_guard_bounded_reverification",
        }
        verified.append(item)
        by_domain[domain].append(item)

    queue = []
    for domain, businesses in sorted(by_domain.items()):
        parts = urlsplit(str(businesses[0]["website"]))
        origin = urlunsplit((parts.scheme, parts.netloc, "", "", ""))
        queue.append({
            "company": businesses[0]["company"],
            "city": businesses[0]["city"],
            "province": businesses[0]["province"],
            "website": origin + "/",
            "url": origin + "/",
            "domain": domain,
            "priority_urls": [origin + path for path in PATHS],
            "directory_record_ids": [row["directory_record_id"] for row in businesses],
            "business_count": len(businesses),
            "businesses": businesses,
            "source": "fresh_hardened_verified_mapping_crawl",
        })
    summary = {
        "input_records": len(rows), "verified_mappings": len(verified),
        "crawl_domains": len(queue),
        "shared_domains": sum(item["business_count"] > 1 for item in queue),
        "priority_paths": list(PATHS), "network_requests": 0,
        "crm_writes": 0, "outreach_actions": 0,
    }
    write_json(output / "verified_mappings.json", sorted(verified, key=lambda x: x["directory_record_id"]))
    write_json(output / "crawl_queue.json", queue)
    write_json(output / "prepare_summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verification", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.verification, args.output_dir), indent=2))


if __name__ == "__main__":
    main()
