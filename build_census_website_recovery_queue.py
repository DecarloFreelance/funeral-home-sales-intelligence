#!/usr/bin/env python3
"""Build a LangSearch discovery queue for census candidates with no website.

`resolve_955_websites.py` is dataset-agnostic: it only needs a bare JSON list
of rows with `company`/`city`/`province`/`directory_record_id` (see
docs/PIPELINE_HISTORY.md). This is the bridge from
compare_census_workbook.py's new-candidate output (rows sourced from
official provincial regulator directories with a phone/email but no website
on file) to that input shape, mirroring
build_v26_website_recovery_queue.py's approach for the live portal dataset.

Candidates are not yet in data/portal_findings.json, so they get a
provisional `CENSUS-NOWEB-<PROVINCE>-####` id, distinct from the
`CENSUS-<PROVINCE>-####` ids build_census_crawl_queue.py assigns to
candidates that already had a website. Performs no searching, no crawling,
and no network access.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

COMPARISON_SOURCE = Path("data/generated/enrichment/census_2026_09_comparison.json")
OUTPUT = Path("data/generated/enrichment/census_website_recovery_queue.json")


class SourceValidationError(ValueError):
    """The comparison artifact does not have the expected shape."""


def load_no_website_candidates(source: Path) -> list[dict]:
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

    without_website = []
    for row in candidates:
        if not isinstance(row, dict):
            raise SourceValidationError("Every candidate must be an object")
        if not row.get("website"):
            without_website.append(row)
    return without_website


def build_queue(source: Path) -> tuple[list, dict]:
    candidates = load_no_website_candidates(source)
    candidates.sort(key=lambda row: (row.get("province", ""), row.get("name", "")))

    province_counters: dict[str, int] = defaultdict(int)
    queue = []
    for index, row in enumerate(candidates):
        province = row.get("province") or "XX"
        province_counters[province] += 1
        directory_record_id = f"CENSUS-NOWEB-{province}-{province_counters[province]:04d}"

        queue.append({
            "directory_record_id": directory_record_id,
            "directory_index": index,
            "company": row.get("name", ""),
            "city": row.get("city", ""),
            "province": province,
            "website_status": "",
        })

    summary = {
        "source": str(source),
        "candidates_without_website": len(candidates),
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
