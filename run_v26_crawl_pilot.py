#!/usr/bin/env python3
"""Bounded pilot: crawl a deterministic slice of the V26 crawl queue.

Thin adapter, not a new crawler: it selects up to `--count` entries
starting at `--offset` (by `directory_index`, already a stable sort on
`directory_record_id`) from `build_v26_crawl_queue.py`'s output and feeds
them straight into the
existing `website_crawler.crawl_queue()` / `PriorityPageCrawler` -- no
crawling logic is duplicated or modified here.

Deliberately does not: touch `data/portal_findings.json`, run
`EnrichmentAgent`/`QualityControlAgent`, write to any CRM/database, or
perform any outreach action. Raw crawl evidence and the crawler's own
report are written to their own generated paths, separate from every
existing production artifact.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from website_crawler import crawl_queue

QUEUE = Path("data/generated/enrichment/v26_crawl_queue.json")
PILOT_QUEUE_OUTPUT = Path("data/generated/enrichment/v26_crawl_pilot_queue.json")
PAGES_OUTPUT = Path("data/generated/enrichment/v26_crawl_pilot_pages.json")
REPORT_OUTPUT = Path("data/generated/enrichment/v26_crawl_pilot_pages_report.json")


class PilotError(ValueError):
    """The queue input does not have the expected shape."""


def select_pilot_batch(queue_path: Path, count: int, offset: int = 0) -> list:
    if not queue_path.is_file():
        raise PilotError(f"Queue file not found: {queue_path}")
    try:
        queue = json.loads(queue_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PilotError(f"Queue file is not valid JSON: {exc}") from exc
    if not isinstance(queue, list):
        raise PilotError("Queue file must contain a JSON list")
    if any(not isinstance(row, dict) or "directory_index" not in row for row in queue):
        raise PilotError("Every queue entry must be an object with a 'directory_index'")

    ordered = sorted(queue, key=lambda row: row["directory_index"])
    sliced = ordered[offset:]
    return sliced[:count] if count else sliced


def run_pilot(
    queue_path: Path = QUEUE,
    count: int = 10,
    offset: int = 0,
    pilot_queue_output: Path = PILOT_QUEUE_OUTPUT,
    pages_output: Path = PAGES_OUTPUT,
    report_output: Path = REPORT_OUTPUT,
    **crawl_kwargs,
) -> dict:
    batch = select_pilot_batch(queue_path, count, offset)

    pilot_queue_output.parent.mkdir(parents=True, exist_ok=True)
    pilot_queue_output.write_text(
        json.dumps(batch, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    report = crawl_queue(
        pilot_queue_output,
        pages_output,
        report_path=report_output,
        **crawl_kwargs,
    )

    return {
        "queue_source": str(queue_path),
        "offset": offset,
        "pilot_batch_size": len(batch),
        "pilot_queue_output": str(pilot_queue_output),
        "pages_output": str(pages_output),
        "report_output": str(report_output),
        "queued_domains": report["queued_domains"],
        "successful_domains": report["successful_domains"],
        "failed_domains": report["failed_domains"],
        "pages": report["pages"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=QUEUE)
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--pilot-queue-output", type=Path, default=PILOT_QUEUE_OUTPUT)
    parser.add_argument("--pages-output", type=Path, default=PAGES_OUTPUT)
    parser.add_argument("--report-output", type=Path, default=REPORT_OUTPUT)
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--max-pages", type=int, default=12)
    parser.add_argument("--max-attempts", type=int, default=12)
    parser.add_argument("--delay", type=float, default=0.25)
    args = parser.parse_args()

    try:
        summary = run_pilot(
            queue_path=args.queue,
            count=args.count,
            offset=args.offset,
            pilot_queue_output=args.pilot_queue_output,
            pages_output=args.pages_output,
            report_output=args.report_output,
            timeout=args.timeout,
            max_pages=args.max_pages,
            max_attempts=args.max_attempts,
            delay=args.delay,
            progress=True,
        )
    except PilotError as exc:
        print(f"REFUSED: {exc}")
        return 1

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
