#!/usr/bin/env python3
"""Merge VERIFIED census candidates into data/portal_findings.json.

Reads extract_census_enrichment.py's output, takes only qc_status ==
"VERIFIED" records, and appends them to the live V26 portal dataset with a
real directory_record_id (continuing each province's existing numeric
sequence -- the census-comparison "CENSUS-<PROVINCE>-####" ids were only ever
provisional).

Contact-field safety: when a record's crawled domain has more than one
distinct address on the page (shared corporate/multi-location sites, e.g.
several branches listed on one page), the fact-extraction step cannot tell
which phone/email belongs to which specific branch, so this script leaves
`emails`/`phones` empty for that record rather than risk attributing a
sibling branch's contact info -- the confirmed company/city/province/website
still gets added. Single-location domains get their full JSON-LD-sourced
contact facts.

Performs no crawling and no network access; does not upload anything to
Render -- that remains a separate manual step (see README.md).
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

EXTRACTION_SOURCE = Path("data/generated/enrichment/census_extraction_results.json")
PORTAL_PATH = Path("data/portal_findings.json")
EXPECTED_PORTAL_VERSION = "V26"
JSONLD_DETECTOR = "jsonld_localbusiness"
DEFAULT_SCORE = 10


class MergeError(ValueError):
    """The extraction or portal source does not meet the required shape."""


def _load_json(path: Path, label: str) -> dict:
    if not path.is_file():
        raise MergeError(f"{label} not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MergeError(f"{label} is not valid JSON: {exc}") from exc


def next_ids_by_province(portal_records: list[dict]) -> dict[str, int]:
    max_ids: dict[str, int] = {}
    for record in portal_records:
        match = re.match(r"^([A-Z]{2})-(\d+)$", str(record.get("directory_record_id", "")))
        if match:
            province, number = match.group(1), int(match.group(2))
            max_ids[province] = max(max_ids.get(province, 0), number)
    return max_ids


def build_new_record(verified: dict, directory_record_id: str) -> tuple[dict, bool]:
    facts = verified.get("facts", [])
    address_facts = [f for f in facts if f.get("field") == "address" and f.get("detector") == JSONLD_DETECTOR]
    distinct_locations = {
        (a["value"].get("city", ""), a["value"].get("province", "")) for a in address_facts
    }
    single_location = len(distinct_locations) <= 1

    emails: list[str] = []
    phones: list[str] = []
    if single_location:
        emails = sorted({f["value"] for f in facts if f.get("field") == "email" and f.get("detector") == JSONLD_DETECTOR})
        phones = sorted({f["value"] for f in facts if f.get("field") == "phone" and f.get("detector") == JSONLD_DETECTOR})

    record = {
        "company": verified.get("company", ""),
        "city": verified.get("city", ""),
        "province": verified.get("province", ""),
        "website": verified.get("website", ""),
        "website_status": "verified",
        "record_type": "Branch",
        "founded_year": "",
        "ownership_type": "",
        "service_area": "",
        "service_offering": "",
        "languages_offered": "",
        "parent_organization": "",
        "staff": [],
        "source": verified.get("website", ""),
        "emails": emails,
        "phones": phones,
        "decision_makers": [],
        "website_verification": True,
        "enrichment_status": "verified",
        "score": DEFAULT_SCORE,
        "directory_record_id": directory_record_id,
    }
    return record, single_location


def build_merge(extraction_path: Path, portal_path: Path) -> tuple[dict, dict]:
    extraction = _load_json(extraction_path, "Extraction artifact")
    portal = _load_json(portal_path, "Portal source")

    if portal.get("version") != EXPECTED_PORTAL_VERSION:
        raise MergeError(
            f"Portal version is {portal.get('version')!r}, expected {EXPECTED_PORTAL_VERSION!r}"
        )
    records = portal.get("records")
    if not isinstance(records, list):
        raise MergeError("Portal 'records' must be a list")

    verified = [r for r in extraction.get("records", []) if r.get("qc_status") == "VERIFIED"]
    verified.sort(key=lambda r: r["directory_record_id"])

    next_ids = next_ids_by_province(records)
    added = []
    contact_suppressed = []
    for row in verified:
        province = row.get("province") or "XX"
        next_ids[province] = next_ids.get(province, 0) + 1
        new_id = f"{province}-{next_ids[province]:04d}"
        new_record, single_location = build_new_record(row, new_id)
        added.append(new_record)
        if not single_location:
            contact_suppressed.append(new_id)

    merged_records = records + added
    provinces = {}
    for record in merged_records:
        province = record.get("province", "")
        provinces[province] = provinces.get(province, 0) + 1

    merged_portal = {
        **portal,
        "generated": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "records": merged_records,
        "summary": {**portal.get("summary", {}), "total_records": len(merged_records), "provinces": provinces},
    }

    summary = {
        "candidates_added": len(added),
        "contact_fields_suppressed_multi_location": contact_suppressed,
        "previous_total": len(records),
        "new_total": len(merged_records),
        "added_ids": [r["directory_record_id"] for r in added],
    }
    return merged_portal, summary


def write_merge(extraction_path: Path, portal_path: Path, output_path: Path) -> dict:
    merged_portal, summary = build_merge(extraction_path, portal_path)
    output_path.write_text(
        json.dumps(merged_portal, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extraction", type=Path, default=EXTRACTION_SOURCE)
    parser.add_argument("--portal", type=Path, default=PORTAL_PATH)
    parser.add_argument("--output", type=Path, default=PORTAL_PATH)
    args = parser.parse_args()

    try:
        summary = write_merge(args.extraction, args.portal, args.output)
    except MergeError as exc:
        print(f"REFUSED: {exc}")
        return 1

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
