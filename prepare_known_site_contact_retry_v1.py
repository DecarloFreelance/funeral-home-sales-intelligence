#!/usr/bin/env python3
"""Prepare a bounded contact/staff path retry for verified single-business sites."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from audit_merge_falconer_v7 import write_json


BASE = Path("data/generated/directory_955")
SOURCE = BASE / "full_955_enrichment_v16/full_955_enrichment.json"
MAPPINGS = BASE / "verified_crawlset/business_website_mappings.json"
OUTPUT = BASE / "known_site_contact_retry_v1"
SOURCE_SHA256 = "78dceed53888b09815af77953cea6e2439021d238d63e70f63a290e3ad806c48"
MAPPINGS_SHA256 = "495ca77881b05ac8a4fcfd79d1068410a06bd8e814b763d1aeeb5dc536eae4ad"
PATHS = ("/", "/contact", "/contact-us", "/about", "/about-us", "/staff", "/our-staff")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def origin(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError(f"Unsafe website URL: {value}")
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def prepare(source: Path, mappings_path: Path, output: Path) -> dict:
    if sha256(source) != SOURCE_SHA256:
        raise ValueError("V16 source drift detected")
    if sha256(mappings_path) != MAPPINGS_SHA256:
        raise ValueError("Verified mapping source drift detected")
    records = json.loads(source.read_text(encoding="utf-8"))
    mappings = json.loads(mappings_path.read_text(encoding="utf-8"))
    if len(records) != 955 or len({r["directory_record_id"] for r in records}) != 955:
        raise ValueError("V16 must contain 955 unique records")
    by_id = {r["directory_record_id"]: r for r in records}
    domain_counts = Counter(row["domain"] for row in mappings)
    queue = []
    for mapping in mappings:
        record = by_id[mapping["directory_record_id"]]
        enrichment = record.get("branch_safe_enrichment") or {}
        if enrichment.get("has_any_contact"):
            continue
        if mapping.get("verification_class") != "ORIGINAL_SELECTED":
            continue
        if domain_counts[mapping["domain"]] != 1:
            continue
        base = origin(mapping["website"])
        queue.append({
            "directory_record_id": mapping["directory_record_id"],
            "company": mapping["company"], "city": mapping["city"],
            "province": mapping["province"], "expected_domain": mapping["domain"],
            "source_website": mapping["website"],
            "candidates": [{"url": base + path, "recovery_class": "KNOWN_FIRST_PARTY_TARGETED_PATH", "recovery_score": 100, "score_reasons": ["original_selected", "single_business_domain", path]} for path in PATHS],
        })
    queue.sort(key=lambda row: row["directory_record_id"])
    if len(queue) != 15:
        raise ValueError(f"Expected 15 retry businesses, got {len(queue)}")
    mapped_ids = {row["directory_record_id"] for row in mappings}
    langsearch_queue = []
    for record in records:
        if record["directory_record_id"] in mapped_ids:
            continue
        langsearch_queue.append({**record, "reason": "no_verified_website"})
    if len(langsearch_queue) != 425:
        raise ValueError(f"Expected 425 LangSearch discovery records, got {len(langsearch_queue)}")
    summary = {
        "source": str(source), "source_sha256": sha256(source),
        "mappings": str(mappings_path), "mappings_sha256": sha256(mappings_path),
        "businesses": len(queue), "domains": len({r["expected_domain"] for r in queue}),
        "candidate_requests": sum(len(r["candidates"]) for r in queue),
        "langsearch_discovery_records": len(langsearch_queue),
        "paths": list(PATHS), "network_requests": 0, "crm_writes": 0,
    }
    write_json(output / "fetch_queue.json", queue)
    write_json(output / "langsearch_unverified_queue.json", langsearch_queue)
    write_json(output / "prepare_summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--mappings", type=Path, default=MAPPINGS)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.mappings, args.output), indent=2))


if __name__ == "__main__":
    main()
