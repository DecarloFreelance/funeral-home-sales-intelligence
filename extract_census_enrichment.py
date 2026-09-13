#!/usr/bin/env python3
"""Per-candidate crawl-evidence extraction for census new-business candidates.

extract_v26_enrichment.py iterates the crawl *report*'s one entry per unique
crawled domain, which is the right behavior for its own purpose but means
only one queue entry per shared domain gets evaluated -- fine when a shared
domain's other entries are branches of a company already otherwise
established, but here every queue entry from build_census_crawl_queue.py is
an unconfirmed candidate, so each one needs its own VERIFIED/REVIEW/
UNRESOLVED classification even when it shares a domain (and a crawl) with
another candidate.

This reuses extract_v26_enrichment.py's detectors and classifier unmodified,
iterating the queue instead of the report: every queue entry gets facts
extracted from its domain's crawled pages and a classification against its
OWN city/province, so e.g. three branches of one association sharing one
domain are each evaluated independently rather than only the last-crawled
one. Performs no crawling and no network access; does not modify
data/portal_findings.json.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict

from extract_v26_enrichment import (
    EXTRACTOR_VERSION,
    _sha256,
    classify_record,
    extract_breadcrumb_navigation,
    extract_jsonld_business_facts,
    extract_text_and_role_facts,
)
from enrichment.evidence import iso, utc_now

ARTIFACT_VERSION = "census-extraction-v1"

DEFAULT_PAGES = Path("data/generated/enrichment/census_crawl_pilot_pages.json")
DEFAULT_REPORT = Path("data/generated/enrichment/census_crawl_pilot_pages_report.json")
DEFAULT_QUEUE = Path("data/generated/enrichment/census_crawl_queue.json")
DEFAULT_OUTPUT = Path("data/generated/enrichment/census_extraction_results.json")


class ExtractionError(ValueError):
    """The input artifacts do not have the expected shape."""


def build_enrichment(
    pages_path: Path, report_path: Path, queue_path: Path, observed_at=None,
) -> Dict[str, Any]:
    observed_at = observed_at or utc_now()

    for label, path in (("Pages", pages_path), ("Report", report_path), ("Queue", queue_path)):
        if not path.is_file():
            raise ExtractionError(f"{label} artifact not found: {path}")

    try:
        pages = json.loads(pages_path.read_text(encoding="utf-8"))
        report = json.loads(report_path.read_text(encoding="utf-8"))
        queue = json.loads(queue_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ExtractionError(f"Input artifact is not valid JSON: {exc}") from exc

    if not isinstance(pages, list) or not isinstance(queue, list) or not isinstance(report, dict):
        raise ExtractionError("Unexpected shape: pages/queue must be lists, report must be an object")

    pages_by_domain: Dict[str, list] = {}
    for page in pages:
        pages_by_domain.setdefault(page.get("domain", ""), []).append(page)

    crawl_status_by_domain = {
        lead.get("domain", ""): lead.get("status", "FAILED") for lead in (report.get("leads") or [])
    }
    domain_counts = Counter(row.get("domain", "") for row in queue)

    records_out = []
    for row in queue:
        directory_record_id = row.get("directory_record_id")
        if not directory_record_id:
            continue
        domain = row.get("domain", "")
        domain_pages = pages_by_domain.get(domain, [])
        record_city = row.get("city", "")
        record_province = row.get("province", "")
        shared_domain = domain_counts.get(domain, 0) > 1
        crawl_status = crawl_status_by_domain.get(domain, "FAILED")

        jsonld_facts = extract_jsonld_business_facts(directory_record_id, domain, domain_pages, observed_at)
        text_role_facts = extract_text_and_role_facts(directory_record_id, domain, domain_pages, observed_at)
        navigation = extract_breadcrumb_navigation(directory_record_id, domain_pages)
        record_facts = jsonld_facts + text_role_facts

        qc = classify_record(record_facts, crawl_status, shared_domain, record_city, record_province)

        records_out.append({
            "directory_record_id": directory_record_id,
            "company": row.get("company", ""),
            "domain": domain,
            "website": row.get("website", ""),
            "city": record_city,
            "province": record_province,
            "qc_status": qc["status"],
            "qc_reasons": qc["reasons"],
            "crawl_linkage": {
                "crawl_status": crawl_status,
                "shared_domain": shared_domain,
                "pages_available": len(domain_pages),
            },
            "facts": record_facts,
            "navigation": navigation,
        })

    records_out.sort(key=lambda r: r["directory_record_id"])

    status_counts = Counter(r["qc_status"] for r in records_out)
    detector_counts = Counter(f["detector"] for r in records_out for f in r["facts"])

    return {
        "version": ARTIFACT_VERSION,
        "generated_at": iso(observed_at),
        "extractor_version": EXTRACTOR_VERSION,
        "input": {
            "pages_artifact": str(pages_path),
            "pages_sha256": _sha256(pages_path),
            "report_artifact": str(report_path),
            "report_sha256": _sha256(report_path),
            "queue_artifact": str(queue_path),
            "queue_sha256": _sha256(queue_path),
        },
        "records": records_out,
        "summary": {
            "records_total": len(records_out),
            "verified": status_counts.get("VERIFIED", 0),
            "review": status_counts.get("REVIEW", 0),
            "unresolved": status_counts.get("UNRESOLVED", 0),
            "facts_total": sum(len(r["facts"]) for r in records_out),
            "facts_by_detector": dict(sorted(detector_counts.items())),
            "navigation_total": sum(len(r["navigation"]) for r in records_out),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", type=Path, default=DEFAULT_PAGES)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    try:
        result = build_enrichment(args.pages, args.report, args.queue)
    except ExtractionError as exc:
        print(f"REFUSED: {exc}")
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], indent=2))
    print(f"Written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
