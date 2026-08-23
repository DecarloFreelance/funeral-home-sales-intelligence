#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

from discovery.crawler import PriorityPageCrawler


DEFAULT_INPUT = Path("data/crawl_queue.json")
DEFAULT_OUTPUT = Path("data/discovered_leads.json")


def merge_crawl_reports(existing, incoming):
    leads = {
        lead.get("domain"): lead
        for lead in [*(existing.get("leads") or []), *(incoming.get("leads") or [])]
        if lead.get("domain")
    }
    values = list(leads.values())
    return {
        "queued_domains": len(values),
        "successful_domains": sum(lead.get("status") == "SUCCESS" for lead in values),
        "failed_domains": [
            lead["domain"] for lead in values if lead.get("status") != "SUCCESS"
        ],
        "pages": sum(int(lead.get("pages", 0)) for lead in values),
        "leads": values,
    }


def crawl_queue(
    input_path: Path,
    output_path: Path,
    timeout=15,
    max_pages=12,
    max_attempts=12,
    limit=None,
    offset=0,
    delay=0.25,
    append=False,
    progress=False,
    progress_callback=None,
    report_path=None,
):
    leads = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(leads, list):
        raise ValueError("Crawl queue must contain a JSON list")

    crawler = PriorityPageCrawler(
        timeout=timeout,
        max_pages_per_lead=max_pages,
        max_attempts_per_lead=max_attempts,
        delay=delay,
    )
    selected = leads[offset:]
    if limit is not None:
        selected = selected[:limit]

    callback = progress_callback
    if progress and callback is None:
        callback = lambda index, total, domain, pages: print(
            f"[{index}/{total}] {domain}: {pages} pages", flush=True,
        )
    records = crawler.crawl_queue(selected, on_lead=callback)

    if append and output_path.exists():
        existing = json.loads(output_path.read_text(encoding="utf-8"))
        if not isinstance(existing, list):
            raise ValueError("Existing crawler output must contain a JSON list")
        records = list({
            record.get("url"): record
            for record in [*existing, *records]
            if record.get("url")
        }.values())

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(records, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output_path)

    report = crawler.last_report
    if report_path is not None:
        if append and report_path.exists():
            existing_report = json.loads(report_path.read_text(encoding="utf-8"))
            report = merge_crawl_reports(existing_report, report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_temporary = report_path.with_suffix(report_path.suffix + ".tmp")
        report_temporary.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        report_temporary.replace(report_path)

    return crawler.last_report


def main():
    parser = argparse.ArgumentParser(
        description="Crawl queued funeral-home contact and business pages."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--max-pages", type=int, default=12)
    parser.add_argument("--max-attempts", type=int, default=12)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--delay", type=float, default=0.25)
    parser.add_argument("--append", action="store_true")
    parser.add_argument("--report-output", type=Path)
    args = parser.parse_args()

    report_path = args.report_output or args.output.with_name(
        args.output.stem + "_report.json"
    )
    report = crawl_queue(
        args.input,
        args.output,
        timeout=args.timeout,
        max_pages=args.max_pages,
        max_attempts=args.max_attempts,
        limit=args.limit,
        offset=args.offset,
        delay=args.delay,
        append=args.append,
        progress=True,
        report_path=report_path,
    )
    print(
        f"Crawled {report['pages']} pages across "
        f"{report['successful_domains']}/{report['queued_domains']} domains "
        f"into {args.output}"
    )
    if report["failed_domains"]:
        print("No pages retrieved for: " + ", ".join(report["failed_domains"]))
    print(f"Saved crawl report to {report_path}")


if __name__ == "__main__":
    main()
