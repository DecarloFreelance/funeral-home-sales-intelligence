#!/usr/bin/env python3
"""Export census candidates awaiting manual review as CSV.

Two files: REVIEW-status crawled candidates (from
extract_census_enrichment.py's output) with their best-guess contact facts,
and no-website candidates (from compare_census_workbook.py's output) that
were never crawlable at all. Neither has been merged into
data/portal_findings.json -- these are for a human to look through and
decide. Performs no crawling and no network access.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

EXTRACTION_SOURCE = Path("data/generated/enrichment/census_extraction_results.json")
COMPARISON_SOURCE = Path("data/generated/enrichment/census_2026_09_comparison.json")
REVIEW_OUTPUT = Path("data/generated/enrichment/census_review_candidates.csv")
NO_WEBSITE_OUTPUT = Path("data/generated/enrichment/census_no_website_candidates.csv")


class SourceValidationError(ValueError):
    """A source artifact does not have the expected shape."""


def _load_json(path: Path, label: str) -> dict:
    if not path.is_file():
        raise SourceValidationError(f"{label} not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SourceValidationError(f"{label} is not valid JSON: {exc}") from exc


def review_rows(extraction: dict) -> list[dict]:
    rows = []
    for record in extraction.get("records", []):
        if record.get("qc_status") != "REVIEW":
            continue
        facts = record.get("facts", [])
        emails = sorted({f["value"] for f in facts if f.get("field") == "email"})
        phones = sorted({f["value"] for f in facts if f.get("field") == "phone"})
        rows.append({
            "directory_record_id": record.get("directory_record_id", ""),
            "company": record.get("company", ""),
            "city": record.get("city", ""),
            "province": record.get("province", ""),
            "website": record.get("website", ""),
            "emails_found": "; ".join(emails),
            "phones_found": "; ".join(phones),
            "reasons": "; ".join(record.get("qc_reasons", [])),
        })
    rows.sort(key=lambda r: (r["province"], r["company"]))
    return rows


def no_website_rows(comparison: dict) -> list[dict]:
    rows = []
    for candidate in comparison.get("new_candidates", []):
        if candidate.get("website"):
            continue
        rows.append({
            "name": candidate.get("name", ""),
            "city": candidate.get("city", ""),
            "province": candidate.get("province", ""),
            "street_address": candidate.get("street_address", ""),
            "postal_code": candidate.get("postal_code", ""),
            "phone": candidate.get("phone", ""),
            "email": candidate.get("email", ""),
            "contact": candidate.get("contact", ""),
            "source_url": candidate.get("source_url", ""),
        })
    rows.sort(key=lambda r: (r["province"], r["name"]))
    return rows


def write_csv(rows: list[dict], fieldnames: list[str], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_exports(
    extraction_path: Path, comparison_path: Path, review_output: Path, no_website_output: Path,
) -> dict:
    extraction = _load_json(extraction_path, "Extraction artifact")
    comparison = _load_json(comparison_path, "Comparison artifact")

    review = review_rows(extraction)
    no_website = no_website_rows(comparison)

    write_csv(
        review,
        ["directory_record_id", "company", "city", "province", "website",
         "emails_found", "phones_found", "reasons"],
        review_output,
    )
    write_csv(
        no_website,
        ["name", "city", "province", "street_address", "postal_code",
         "phone", "email", "contact", "source_url"],
        no_website_output,
    )

    return {
        "review_count": len(review),
        "review_output": str(review_output),
        "no_website_count": len(no_website),
        "no_website_output": str(no_website_output),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extraction", type=Path, default=EXTRACTION_SOURCE)
    parser.add_argument("--comparison", type=Path, default=COMPARISON_SOURCE)
    parser.add_argument("--review-output", type=Path, default=REVIEW_OUTPUT)
    parser.add_argument("--no-website-output", type=Path, default=NO_WEBSITE_OUTPUT)
    args = parser.parse_args()

    try:
        summary = write_exports(
            args.extraction, args.comparison, args.review_output, args.no_website_output
        )
    except SourceValidationError as exc:
        print(f"REFUSED: {exc}")
        return 1

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
