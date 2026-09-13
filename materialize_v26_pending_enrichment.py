#!/usr/bin/env python3
"""Fill in missing contact evidence for existing pending V26 records.

Unlike materialize_census_verified.py (which adds brand-new records), every
queue entry here already has a directory_record_id in data/portal_findings.json
-- build_v26_crawl_queue.py only selects records that already have a known
website but no emails/phones/staff/decision_makers on file yet. This updates
those existing records in place rather than inserting anything.

Only VERIFIED records (structured schema.org data confirming this specific
branch's address) are merged automatically, and only into fields that are
currently empty -- never overwrites existing emails/phones. Like
materialize_census_verified.py, suppresses contact fields for a record whose
crawled domain shows more than one distinct address on the page, since
fact-extraction can't tell which contact info belongs to which branch.
REVIEW/UNRESOLVED records are left untouched for manual follow-up (see
export_census_review_candidates.py's pattern -- reuse that CSV shape for
these too if needed).

Performs no crawling and no network access; does not upload anything to
Render -- that remains a separate manual step (see README.md).
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

EXTRACTION_SOURCE = Path("data/generated/enrichment/v26_pending_extraction_results.json")
PORTAL_PATH = Path("data/portal_findings.json")
EXPECTED_PORTAL_VERSION = "V26"
JSONLD_DETECTOR = "jsonld_localbusiness"


class MergeError(ValueError):
    """The extraction or portal source does not meet the required shape."""


def _load_json(path: Path, label: str) -> dict:
    if not path.is_file():
        raise MergeError(f"{label} not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MergeError(f"{label} is not valid JSON: {exc}") from exc


def contact_updates(verified: dict) -> tuple[list[str], list[str], bool]:
    facts = verified.get("facts", [])
    address_facts = [f for f in facts if f.get("field") == "address" and f.get("detector") == JSONLD_DETECTOR]
    distinct_locations = {
        (a["value"].get("city", ""), a["value"].get("province", "")) for a in address_facts
    }
    single_location = len(distinct_locations) <= 1
    if not single_location:
        return [], [], False

    emails = sorted({f["value"] for f in facts if f.get("field") == "email" and f.get("detector") == JSONLD_DETECTOR})
    phones = sorted({f["value"] for f in facts if f.get("field") == "phone" and f.get("detector") == JSONLD_DETECTOR})
    return emails, phones, True


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

    verified_by_id = {
        r["directory_record_id"]: r
        for r in extraction.get("records", [])
        if r.get("qc_status") == "VERIFIED" and r.get("directory_record_id")
    }

    updated_ids: list[str] = []
    contact_suppressed: list[str] = []
    skipped_no_gap: list[str] = []
    merged_records = []
    for record in records:
        record_id = record.get("directory_record_id")
        verified = verified_by_id.get(record_id)
        if verified is None:
            merged_records.append(record)
            continue

        emails, phones, single_location = contact_updates(verified)
        if not single_location:
            contact_suppressed.append(record_id)
            merged_records.append(record)
            continue

        has_gap = not (record.get("emails") or []) or not (record.get("phones") or [])
        if not has_gap:
            skipped_no_gap.append(record_id)
            merged_records.append(record)
            continue

        new_record = dict(record)
        if not (record.get("emails") or []) and emails:
            new_record["emails"] = emails
        if not (record.get("phones") or []) and phones:
            new_record["phones"] = phones
        if new_record.get("emails") or new_record.get("phones"):
            new_record["website_verification"] = True
            if new_record.get("enrichment_status") == "pending":
                new_record["enrichment_status"] = "verified"
            updated_ids.append(record_id)
        merged_records.append(new_record)

    merged_portal = {
        **portal,
        "generated": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "records": merged_records,
    }

    summary = {
        "updated_count": len(updated_ids),
        "updated_ids": updated_ids,
        "contact_fields_suppressed_multi_location": contact_suppressed,
        "skipped_already_had_contact_evidence": skipped_no_gap,
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
