#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

from discovery.research_queue import build_research_queue


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(
        description="Build an actionable queue for domains without usable crawl pages."
    )
    parser.add_argument("--queue", type=Path, default=Path("data/crawl_queue.json"))
    parser.add_argument("--pages", type=Path, default=Path("data/discovered_leads.json"))
    parser.add_argument("--report", type=Path, default=Path("data/discovered_leads_report.json"))
    parser.add_argument("--output", type=Path, default=Path("data/research_queue.json"))
    args = parser.parse_args()

    report = load_json(args.report) if args.report.exists() else None
    research = build_research_queue(
        load_json(args.queue),
        load_json(args.pages),
        report,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(research, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(args.output)
    print(f"Queued {len(research)} unresolved domains in {args.output}")


if __name__ == "__main__":
    main()
