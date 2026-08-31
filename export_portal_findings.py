#!/usr/bin/env python3
"""Build the minimal private V15 snapshot consumed by the online portal."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


SOURCE = Path("data/generated/directory_955/full_955_enrichment_v15/full_955_enrichment.json")
SUMMARY = Path("data/generated/directory_955/full_955_enrichment_v15/summary.json")
OUTPUT = Path("instance/portal_findings.json")
MAX_RENDER_SECRET_BYTES = 1_000_000


def build(source: Path, summary_path: Path) -> dict:
    records = json.loads(source.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if len(records) != 955 or len({row.get("directory_record_id") for row in records}) != 955:
        raise ValueError("Portal source must contain 955 unique canonical records")
    output = []
    for row in records:
        enrichment = row.get("branch_safe_enrichment") or {}
        output.append({
            "directory_record_id": row.get("directory_record_id", ""),
            "company": row.get("company", ""), "city": row.get("city", ""),
            "province": row.get("province", ""),
            "emails": [item.get("value", "") for item in enrichment.get("emails") or []],
            "phones": [item.get("value", "") for item in enrichment.get("phones") or []],
            "staff": [{"name": item.get("name", ""), "title": item.get("title", "")} for item in enrichment.get("staff") or []],
            "decision_makers": [{"name": item.get("name", ""), "title": item.get("title", "")} for item in enrichment.get("decision_makers") or []],
            "has_any_contact": bool(enrichment.get("has_any_contact")),
        })
    return {"version": "V15", "records": output, "summary": summary}


def write_snapshot(source: Path, summary: Path, output: Path) -> int:
    payload = json.dumps(build(source, summary), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
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
    args = parser.parse_args()
    print(json.dumps({"records": 955, "bytes": write_snapshot(args.source, args.summary, args.output), "output": str(args.output)}))


if __name__ == "__main__":
    main()
