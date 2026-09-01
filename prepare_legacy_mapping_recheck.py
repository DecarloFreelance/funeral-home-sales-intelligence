#!/usr/bin/env python3
"""Build a fail-closed current-guard re-verification queue for legacy mappings."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from audit_merge_falconer_v7 import write_json
from verify_langsearch_recovery_v2 import domain_supports_company, identity_domain_label

BASE = Path("data/generated/directory_955")
DEFAULT_MAPPINGS = BASE / "verified_crawlset/business_website_mappings.json"
DEFAULT_OUTPUT = BASE / "legacy_mapping_recheck_v1"


def prepare(mappings_path: Path, output: Path) -> dict:
    mappings = json.loads(mappings_path.read_text(encoding="utf-8"))
    if not isinstance(mappings, list):
        raise ValueError("Mappings must be a JSON list")

    seen: set[str] = set()
    queue = []
    searches = []
    quarantine = []
    eligible_domains: set[str] = set()

    for mapping in mappings:
        record_id = str(mapping.get("directory_record_id") or "")
        if not record_id or record_id in seen:
            raise ValueError(f"Missing or duplicate directory_record_id: {record_id!r}")
        seen.add(record_id)
        website = str(mapping.get("website") or "")
        try:
            parts = urlsplit(website)
            host = (parts.hostname or "").casefold().rstrip(".")
        except ValueError:
            host = ""
        company = str(mapping.get("company") or "")
        common = {
            "directory_record_id": record_id,
            "directory_index": int(record_id.removeprefix("CFI-") or 0),
            "company": company,
            "city": str(mapping.get("city") or ""),
            "province": str(mapping.get("province") or ""),
        }
        supported = (
            parts.scheme in {"http", "https"}
            and bool(host)
            and parts.username is None
            and parts.password is None
            and domain_supports_company(host, company)
        )
        if not supported:
            quarantine.append({
                **common,
                "website": website,
                "host": host,
                "identity_domain_label": identity_domain_label(host),
                "reason": "current_first_party_identity_guard_rejected",
                "prior_verification_class": mapping.get("verification_class"),
                "network_requests": 0,
            })
            continue

        queue.append(common)
        searches.append({
            "directory_record_id": record_id,
            "status": "OK",
            "results": [{
                "rank": 1,
                "url": website,
                "name": company,
                "snippet": f"Existing legacy mapping for {company}",
                "_existing_candidate": True,
                "prior_verification_class": mapping.get("verification_class"),
                "prior_source": mapping.get("source"),
            }],
        })
        eligible_domains.add(host.removeprefix("www."))

    summary = {
        "mapping_records": len(mappings),
        "eligible_records": len(queue),
        "eligible_domains": len(eligible_domains),
        "quarantined_records": len(quarantine),
        "network_requests": 0,
        "crm_writes": 0,
        "outreach_actions": 0,
    }
    write_json(output / "queue.json", queue)
    write_json(output / "search_results.json", searches)
    write_json(output / "quarantine.json", quarantine)
    write_json(output / "prepare_summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mappings", type=Path, default=DEFAULT_MAPPINGS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(prepare(args.mappings, args.output_dir), indent=2))


if __name__ == "__main__":
    main()
