#!/usr/bin/env python3
"""Prepare the bounded V17 crawl from verified first-party website evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from audit_merge_falconer_v7 import write_json
from verify_langsearch_recovery_v2 import enforce_first_party

BASE = Path("data/generated/directory_955")
V16 = BASE / "full_955_enrichment_v16/full_955_enrichment.json"
VERIFIED = BASE / "langsearch_unverified_v2/verification/verified_websites.json"
EXISTING = BASE / "verified_crawlset/business_website_mappings.json"
OUTPUT = BASE / "v17_verified_recovery_v1"
V16_SHA256 = "78dceed53888b09815af77953cea6e2439021d238d63e70f63a290e3ad806c48"
EXPLICIT_EXISTING_TARGETS = {"CFI-0658", "CFI-0948"}
PATHS = ("/", "/contact", "/contact-us", "/about", "/about-us", "/staff", "/team",
         "/our-team", "/meet-the-team", "/directors", "/funeral-directors", "/locations")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(output: Path = OUTPUT) -> dict:
    if sha256(V16) != V16_SHA256:
        raise ValueError("V16 source drift detected")
    canonical = json.loads(V16.read_text(encoding="utf-8"))
    verified = json.loads(VERIFIED.read_text(encoding="utf-8"))
    existing = json.loads(EXISTING.read_text(encoding="utf-8"))
    by_id = {row["directory_record_id"]: row for row in canonical}
    accepted = []
    for row in verified:
        guarded = enforce_first_party(row)
        if guarded.get("status") not in {"VERIFIED", "VERIFIED_HIGH"}:
            continue
        accepted.append({
            "directory_record_id": row["directory_record_id"], "company": row["company"],
            "city": row["city"], "province": row["province"], "website": row["website"],
            "domain": (urlsplit(row["website"]).hostname or "").removeprefix("www."),
            "verification_class": "LANGSEARCH_VERIFIED_FIRST_PARTY",
            "verification_score": row["verification_score"],
            "source": "langsearch_v2_plus_first_party_verification",
        })
    for row in existing:
        if row.get("directory_record_id") in EXPLICIT_EXISTING_TARGETS:
            if row.get("verification_class") != "ORIGINAL_SELECTED":
                raise ValueError("Explicit V17 target is not an existing verified selection")
            accepted.append(row)
    mappings = {row["directory_record_id"]: row for row in accepted}
    if len(mappings) != len(accepted) or set(EXPLICIT_EXISTING_TARGETS) - set(mappings):
        raise ValueError("Duplicate or missing V17 recovery mapping")
    queue = []
    for record_id, mapping in sorted(mappings.items()):
        if record_id not in by_id:
            raise ValueError(f"Unknown canonical ID: {record_id}")
        parts = urlsplit(mapping["website"])
        origin = urlunsplit((parts.scheme, parts.netloc, "", "", ""))
        queue.append({
            "directory_record_id": record_id, "company": mapping["company"],
            "city": mapping["city"], "province": mapping["province"],
            "domain": mapping["domain"], "url": origin + "/",
            "priority_urls": [origin + path for path in PATHS[1:]],
            "source": mapping["source"], "record_type": "directory_verified",
            "provenance": [{"verification_class": mapping["verification_class"],
                            "verification_score": mapping.get("verification_score")}],
        })
    summary = {"v16_sha256": sha256(V16), "verified_langsearch_records": len(accepted) - 2,
               "explicit_existing_targets": sorted(EXPLICIT_EXISTING_TARGETS),
               "crawl_records": len(queue), "paths": list(PATHS), "network_requests": 0,
               "crm_writes": 0, "outreach_actions": 0}
    write_json(output / "verified_mappings.json", sorted(mappings.values(), key=lambda x: x["directory_record_id"]))
    write_json(output / "crawl_queue.json", queue)
    write_json(output / "quarantine.json", [])
    write_json(output / "prepare_summary.json", summary)
    return summary


if __name__ == "__main__":
    print(json.dumps(prepare(), indent=2))
