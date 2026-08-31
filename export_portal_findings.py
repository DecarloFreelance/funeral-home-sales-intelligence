#!/usr/bin/env python3
"""Build the minimal private V15 snapshot consumed by the online portal."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


SOURCE = Path("data/generated/directory_955/full_955_enrichment_v15/full_955_enrichment.json")
SUMMARY = Path("data/generated/directory_955/full_955_enrichment_v15/summary.json")
OUTPUT = Path("instance/portal_findings.json")
MAPPINGS = Path("data/generated/directory_955/verified_crawlset/business_website_mappings.json")
MAX_RENDER_SECRET_BYTES = 1_000_000


def compact_evidence(item: dict) -> dict:
    return {
        key: item.get(key)
        for key in ("value", "name", "title", "decision_maker", "source_url", "evidence_class")
        if item.get(key) not in (None, "")
    }


def build(source: Path, summary_path: Path, mappings_path: Path | None = None) -> dict:
    records = json.loads(source.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if len(records) != 955 or len({row.get("directory_record_id") for row in records}) != 955:
        raise ValueError("Portal source must contain 955 unique canonical records")
    mappings = {}
    if mappings_path and mappings_path.is_file():
        mapping_rows = json.loads(mappings_path.read_text(encoding="utf-8"))
        mappings = {row["directory_record_id"]: row for row in mapping_rows}
    output = []
    for row in records:
        enrichment = row.get("branch_safe_enrichment") or {}
        mapping = mappings.get(row.get("directory_record_id"), {})
        output.append({
            "directory_record_id": row.get("directory_record_id", ""),
            "company": row.get("company", ""), "city": row.get("city", ""),
            "province": row.get("province", ""),
            "website": mapping.get("website") or row.get("website", ""),
            "website_verification": mapping.get("verification_class") or row.get("website_status", ""),
            "emails": [compact_evidence(item) for item in enrichment.get("emails") or []],
            "phones": [compact_evidence(item) for item in enrichment.get("phones") or []],
            "staff": [compact_evidence(item) for item in enrichment.get("staff") or []],
            "decision_makers": [compact_evidence(item) for item in enrichment.get("decision_makers") or []],
            "has_any_contact": bool(enrichment.get("has_any_contact")),
        })
    return {"version": "V15", "records": output, "summary": summary}


def write_snapshot(source: Path, summary: Path, output: Path, mappings: Path | None = MAPPINGS) -> int:
    payload = json.dumps(build(source, summary, mappings), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    size = len(payload.encode())
    if size > MAX_RENDER_SECRET_BYTES:
        raise ValueError(f"Portal snapshot exceeds Render's 1 MB secret-file limit: {size}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(payload, encoding="utf-8")
    output.chmod(0o600)
    return size


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--summary", type=Path, default=SUMMARY)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--mappings", type=Path, default=MAPPINGS)
    args = parser.parse_args()
    print(json.dumps({"records": 955, "bytes": write_snapshot(args.source, args.summary, args.output, args.mappings), "output": str(args.output)}))


if __name__ == "__main__":
    main()
