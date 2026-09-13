#!/usr/bin/env python3
"""Build a LangSearch discovery queue from the live V26 `data/portal_findings.json`.

`resolve_955_websites.py` is dataset-agnostic: it only needs a bare JSON list
of rows with `company`/`city`/`province`/`directory_record_id` (see
docs/PIPELINE_HISTORY.md). This script is the missing bridge for the current
1,302-record V26 dataset -- it does not touch the retired V14-V19/955-record
pipeline, `export_portal_findings.py`, `/leads`, or the source file itself.

Selects only records with no website on file (`website` empty/missing),
assigns a stable `directory_index` (sorted by `directory_record_id`) so
`resolve_955_websites.py`'s checkpoint ordering is deterministic across runs,
and optionally bounds the output to a small pilot batch with `--limit`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

SOURCE = Path("data/portal_findings.json")
OUTPUT = Path("data/generated/enrichment/v26_website_recovery_queue.json")
REQUIRED_ROW_KEYS = ("directory_record_id", "company", "city", "province")


class SourceValidationError(ValueError):
    """The source artifact does not have the expected portal shape."""


def load_missing_website_rows(source: Path) -> tuple[list[dict], str | None, int]:
    """Return (queue_rows, detected_version, total_record_count).

    Never modifies `source`. Skips (rather than crashes on) individual
    malformed rows, since one bad record should not block discovery for the
    other 1,300+.
    """
    if not source.is_file():
        raise SourceValidationError(f"Source file not found: {source}")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SourceValidationError(f"Source is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        raise SourceValidationError("Source must be a JSON object with a 'records' list")

    records = payload["records"]
    version = payload.get("version")

    candidates = []
    for row in records:
        if not isinstance(row, dict):
            continue
        if any(not str(row.get(key) or "").strip() for key in REQUIRED_ROW_KEYS):
            continue
        if str(row.get("website") or "").strip():
            continue
        candidates.append(row)

    candidates.sort(key=lambda row: str(row["directory_record_id"]))

    queue = [
        {
            "directory_record_id": row["directory_record_id"],
            "directory_index": index,
            "company": row["company"],
            "city": row["city"],
            "province": row["province"],
            "website_status": row.get("website_status", ""),
        }
        for index, row in enumerate(candidates)
    ]
    return queue, version, len(records)


def write_queue(source: Path, output: Path, limit: int = 0) -> dict:
    queue, version, total_records = load_missing_website_rows(source)
    bounded = queue[:limit] if limit else queue

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(bounded, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    return {
        "source": str(source),
        "source_version": version,
        "source_total_records": total_records,
        "missing_website_total": len(queue),
        "queue_written": len(bounded),
        "output": str(output),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Bound the queue to the first N missing-website records (0 = all).",
    )
    args = parser.parse_args()

    try:
        summary = write_queue(args.source, args.output, args.limit)
    except SourceValidationError as exc:
        print(f"REFUSED: {exc}")
        return 1

    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
