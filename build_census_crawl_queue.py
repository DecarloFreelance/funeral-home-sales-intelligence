#!/usr/bin/env python3
"""Build a crawl queue for new-business candidates found by
compare_census_workbook.py.

Reads the `new_candidates` list from a census-comparison artifact, keeps only
rows with a usable website, and writes a queue in the same shape
build_v26_crawl_queue.py produces so it can be fed unmodified into
run_v26_crawl_pilot.py (--queue) and then extract_v26_enrichment.py.

Candidates are not yet in data/portal_findings.json, so they get a
provisional `CENSUS-<PROVINCE>-####` directory_record_id rather than a real
one -- this keeps them visibly distinct from confirmed directory records
until a human reviews crawl results and decides to merge them in. Performs
no crawling and no network access.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

COMPARISON_SOURCE = Path("data/generated/enrichment/census_2026_09_comparison.json")
OUTPUT = Path("data/generated/enrichment/census_crawl_queue.json")
QUEUE_REASON = "CENSUS_NEW_CANDIDATE_WITH_WEBSITE"


class SourceValidationError(ValueError):
    """The comparison artifact does not have the expected shape."""


def load_new_candidates_with_website(source: Path) -> list[dict]:
    if not source.is_file():
        raise SourceValidationError(f"Comparison artifact not found: {source}")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SourceValidationError(f"Comparison artifact is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SourceValidationError("Comparison artifact must be a JSON object")
    candidates = payload.get("new_candidates")
    if not isinstance(candidates, list):
        raise SourceValidationError("Comparison artifact 'new_candidates' must be a list")

    with_website = []
    for row in candidates:
        if not isinstance(row, dict):
            raise SourceValidationError("Every candidate must be an object")
        if row.get("domain") and row.get("website"):
            with_website.append(row)
    return with_website


def build_queue(source: Path) -> tuple[list, dict]:
    candidates = load_new_candidates_with_website(source)
    candidates.sort(key=lambda row: (row.get("province", ""), row.get("name", "")))

    province_counters: dict[str, int] = defaultdict(int)
    queue = []
    for index, row in enumerate(candidates):
        province = row.get("province") or "XX"
        province_counters[province] += 1
        directory_record_id = f"CENSUS-{province}-{province_counters[province]:04d}"

        queue.append({
            "directory_record_id": directory_record_id,
            "directory_index": index,
            "company": row.get("name", ""),
            "city": row.get("city", ""),
            "province": province,
            "website": row["website"],
            "domain": row["domain"],
            "queue_reason": QUEUE_REASON,
        })

    summary = {
        "source": str(source),
        "candidates_with_website": len(candidates),
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
    parser.add_argument("--source", type=Path, default=COMPARISON_SOURCE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    try:
        summary = write_queue(args.source, args.output)
    except SourceValidationError as exc:
        print(f"REFUSED: {exc}")
        return 1

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
