#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

from discovery.resolution import apply_resolutions


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(
        description="Apply reviewed domain resolutions to the research queue."
    )
    parser.add_argument("--research", type=Path, default=Path("data/research_queue.json"))
    parser.add_argument("--resolutions", type=Path, default=Path("data/seeds/domain_resolutions.json"))
    parser.add_argument("--pages", type=Path, default=Path("data/discovered_leads.json"))
    parser.add_argument("--output", type=Path, default=Path("data/resolved_retry_queue.json"))
    parser.add_argument("--summary", type=Path, default=Path("data/resolution_summary.json"))
    parser.add_argument(
        "--remaining-output",
        type=Path,
        default=Path("data/research_queue.json"),
    )
    args = parser.parse_args()

    retry, summary = apply_resolutions(
        load(args.research),
        load(args.resolutions),
        load(args.pages) if args.pages.exists() else [],
    )
    write_json(args.output, retry)
    write_json(args.summary, summary)
    write_json(args.remaining_output, summary["remaining"])
    print(
        f"Prepared {len(retry)} retry domains; "
        f"{len(summary['resolved_existing'])} already covered; "
        f"{summary['remaining_domains']} remain in research"
    )


if __name__ == "__main__":
    main()
