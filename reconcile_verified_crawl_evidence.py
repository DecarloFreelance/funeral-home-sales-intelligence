#!/usr/bin/env python3
"""Filter cached crawl pages to a fresh verified queue and attach provenance."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from audit_merge_falconer_v7 import write_json


def reconcile(queue_path: Path, pages_path: Path, output: Path) -> dict:
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    pages = json.loads(pages_path.read_text(encoding="utf-8"))
    by_domain = {str(row["domain"]).casefold().removeprefix("www."): row for row in queue}
    if len(by_domain) != len(queue):
        raise ValueError("Duplicate crawl domains")
    accepted = {}
    rejected = []
    observed_domains = set()
    for page in pages:
        discovery = page.get("discovery") or {}
        domain = str(discovery.get("queue_domain") or "").casefold().removeprefix("www.")
        mapping = by_domain.get(domain)
        final_host = (urlsplit(str(page.get("url") or "")).hostname or "").casefold().removeprefix("www.")
        if mapping is None or not final_host or not (
            final_host == domain or final_host.endswith("." + domain) or domain.endswith("." + final_host)
        ):
            rejected.append({"url": page.get("url"), "queue_domain": domain,
                             "reason": "not_in_fresh_verified_domain_set"})
            continue
        enriched = {
            **page,
            "discovery": {
                **discovery,
                "directory_record_ids": mapping["directory_record_ids"],
                "businesses": mapping["businesses"],
                "verification_state": "fresh_hardened_verified",
                "verification_source": mapping["source"],
            },
        }
        accepted[(domain, page.get("url"))] = enriched
        observed_domains.add(domain)
    missing = [row for row in queue if row["domain"] not in observed_domains]
    summary = {
        "verified_domains": len(queue), "accepted_unique_pages": len(accepted),
        "domains_with_pages": len(observed_domains), "missing_domains": len(missing),
        "rejected_cached_pages": len(rejected), "crm_writes": 0, "outreach_actions": 0,
    }
    write_json(output / "pages.json", list(accepted.values()))
    write_json(output / "missing_crawl_queue.json", missing)
    write_json(output / "rejected_cached_pages.json", rejected)
    write_json(output / "reconcile_summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--pages", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(reconcile(args.queue, args.pages, args.output_dir), indent=2))


if __name__ == "__main__":
    main()
