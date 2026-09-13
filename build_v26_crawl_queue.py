#!/usr/bin/env python3
"""Build the V26 known-website crawl queue.

Additive, read-only bridge from the authoritative V26 `data/portal_findings.json`
to a bounded crawl target list. Deliberately separate from
`build_v26_website_recovery_queue.py` (which queues records with NO website
for LangSearch *discovery*) -- this script queues records that already HAVE a
website on file but no contact evidence yet, so the site itself can be
crawled next. It performs no crawling, no DNS resolution, and no network
access of any kind: it only reads and validates the source and writes a
queue file. It never touches `data/crawl_queue.json` (a different, unrelated
schema consumed by the existing discovery-import workflow).

Selection (a V26 record qualifies when ALL of):
- `website` is a non-empty string
- `enrichment_status == "pending"`
- `emails`, `phones`, `staff`, and `decision_makers` are all empty

Fails closed (writes nothing) on: missing source, invalid JSON, wrong
version, missing/non-list `records`, a qualifying record missing required
identity fields, a qualifying record's contact-evidence fields having the
wrong type, or a qualifying record's `website` being malformed or unsafe.
Every qualifying record is queued independently -- multiple records sharing
one domain are never merged or deduplicated.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from discovery.network_safety import static_public_hostname

SOURCE = Path("data/portal_findings.json")
OUTPUT = Path("data/generated/enrichment/v26_crawl_queue.json")
EXPECTED_VERSION = "V26"
REQUIRED_IDENTITY_KEYS = ("directory_record_id", "company", "city", "province")
CONTACT_LIST_KEYS = ("emails", "phones", "staff", "decision_makers")
QUEUE_REASON = "KNOWN_WEBSITE_NO_CONTACT_EVIDENCE"


class SourceValidationError(ValueError):
    """The source artifact or a qualifying record does not meet the required shape."""


def normalize_hostname(website: str) -> str:
    """Network-free hostname normalization: validate scheme/hostname, run the
    existing static (no-DNS) public-hostname check, lowercase, and strip a
    leading 'www.'. Raises SourceValidationError on anything unsafe or
    malformed; never resolves DNS or makes a request."""
    parsed = urlsplit(website)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise SourceValidationError(f"Website is not an http(s) URL: {website!r}")
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname:
        raise SourceValidationError(f"Website has no hostname: {website!r}")
    if not static_public_hostname(hostname):
        raise SourceValidationError(
            f"Website hostname failed the static public-hostname check: {website!r}"
        )
    return hostname.removeprefix("www.")


def qualifies(row: dict) -> bool:
    if row.get("enrichment_status") != "pending":
        return False
    if not str(row.get("website") or "").strip():
        return False
    return all(not (row.get(key) or []) for key in CONTACT_LIST_KEYS)


def load_records(source: Path) -> tuple[list, str]:
    if not source.is_file():
        raise SourceValidationError(f"Source file not found: {source}")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SourceValidationError(f"Source is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SourceValidationError("Source must be a JSON object")
    if payload.get("version") != EXPECTED_VERSION:
        raise SourceValidationError(
            f"Source version is {payload.get('version')!r}, expected {EXPECTED_VERSION!r}"
        )
    records = payload.get("records")
    if not isinstance(records, list):
        raise SourceValidationError("Source 'records' must be a list")
    return records, payload["version"]


def build_queue(source: Path) -> tuple[list, dict]:
    records, version = load_records(source)

    qualifying = [row for row in records if isinstance(row, dict) and qualifies(row)]
    qualifying.sort(key=lambda row: str(row.get("directory_record_id") or ""))

    queue = []
    for index, row in enumerate(qualifying):
        missing = [key for key in REQUIRED_IDENTITY_KEYS if not str(row.get(key) or "").strip()]
        if missing:
            raise SourceValidationError(
                f"Qualifying record {row.get('directory_record_id')!r} is missing "
                f"required identity fields: {missing}"
            )
        for key in CONTACT_LIST_KEYS:
            if not isinstance(row.get(key, []), list):
                raise SourceValidationError(
                    f"Qualifying record {row.get('directory_record_id')!r} has a "
                    f"non-list '{key}' field"
                )

        website = str(row["website"]).strip()
        domain = normalize_hostname(website)

        queue.append({
            "directory_record_id": row["directory_record_id"],
            "directory_index": index,
            "company": row["company"],
            "city": row["city"],
            "province": row["province"],
            "website": website,
            "domain": domain,
            "enrichment_status": row.get("enrichment_status", ""),
            "queue_reason": QUEUE_REASON,
        })

    summary = {
        "source_version": version,
        "source_total_records": len(records),
        "queue_count": len(queue),
    }
    return queue, summary


def write_queue(source: Path, output: Path) -> dict:
    queue, summary = build_queue(source)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(queue, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    summary["output"] = str(output)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    try:
        summary = write_queue(args.source, args.output)
    except SourceValidationError as exc:
        print(f"REFUSED: {exc}")
        return 1

    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
