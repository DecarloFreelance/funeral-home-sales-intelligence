#!/usr/bin/env python3

import argparse
from collections import Counter
import json
from pathlib import Path

from discovery.crawler import PriorityPageCrawler


DEFAULT_INPUT = Path("data/crawl_queue.json")
DEFAULT_OUTPUT = Path("data/discovered_leads.json")


def _summarize(leads):
    attempts = Counter(
        attempt.get("outcome")
        for lead in leads for attempt in lead.get("attempts", [])
    )
    durations = sorted(lead.get("duration_ms", 0) for lead in leads)
    return {
        "queued_domains": len(leads),
        "successful_domains": sum(lead.get("status") == "SUCCESS" for lead in leads),
        "failed_domains": [lead["domain"] for lead in leads if lead.get("status") != "SUCCESS"],
        "pages": sum(int(lead.get("pages", 0)) for lead in leads),
        "attempt_outcomes": dict(sorted(attempts.items())),
        "duration_ms": sum(durations),
        "average_domain_duration_ms": round(sum(durations) / len(durations)) if durations else 0,
        "median_domain_duration_ms": durations[len(durations) // 2] if durations else 0,
        "leads": leads,
    }


def merge_crawl_reports(existing, incoming):
    leads = {
        lead.get("domain"): lead
        for lead in [*(existing.get("leads") or []), *(incoming.get("leads") or [])]
        if lead.get("domain")
    }
    values = list(leads.values())
    return _summarize(values)


def _atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


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
    resume=False,
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

    existing_records = []
    existing_report = {"leads": []}
    if append and output_path.exists():
        existing_records = json.loads(output_path.read_text(encoding="utf-8"))
        if not isinstance(existing_records, list):
            raise ValueError("Existing crawler output must contain a JSON list")
    if append and report_path is not None and report_path.exists():
        existing_report = json.loads(report_path.read_text(encoding="utf-8"))
    if resume:
        completed = {item.get("domain") for item in existing_report.get("leads", [])}
        selected = [lead for lead in selected if lead.get("domain") not in completed]

    current_records = {item.get("url"): item for item in existing_records if item.get("url")}
    current_report = existing_report

    def checkpoint(lead_records, lead_report):
        nonlocal current_report
        current_records.update({item.get("url"): item for item in lead_records if item.get("url")})
        current_report = merge_crawl_reports(current_report, {"leads": [lead_report]})
        _atomic_json(output_path, list(current_records.values()))
        if report_path is not None:
            _atomic_json(report_path, current_report)

    callback = progress_callback
    if progress and callback is None:
        callback = lambda index, total, domain, pages: print(
            f"[{index}/{total}] {domain}: {pages} pages", flush=True,
        )
    records = crawler.crawl_queue(selected, on_lead=callback, checkpoint=checkpoint)

    if append:
        records = list(current_records.values())

    _atomic_json(output_path, records)

    report = crawler.last_report
    if report_path is not None:
        if append and report_path.exists():
            existing_report = json.loads(report_path.read_text(encoding="utf-8"))
            report = merge_crawl_reports(existing_report, report)
        _atomic_json(report_path, report)

    return report


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
    parser.add_argument("--resume", action="store_true")
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
        resume=args.resume,
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
