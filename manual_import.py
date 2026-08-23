#!/usr/bin/env python3

import argparse
import csv
import json
from pathlib import Path

from discovery.ingestion import DiscoveryLead, build_crawl_queue


DEFAULT_INPUT = Path("data/seeds/manual_leads.csv")
DEFAULT_OUTPUT = Path("data/crawl_queue.json")


def import_manual_leads(input_path: Path, output_path: Path) -> int:
    with input_path.open(newline="", encoding="utf-8-sig") as source:
        rows = csv.DictReader(source)
        required = {"company", "website"}
        fields = set(rows.fieldnames or [])
        missing = required - fields
        if missing:
            raise ValueError(
                "Missing required CSV columns: " + ", ".join(sorted(missing))
            )

        queue = build_crawl_queue(
            DiscoveryLead.from_mapping(row)
            for row in rows
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(queue, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return len(queue)


def main():
    parser = argparse.ArgumentParser(
        description="Normalize manual funeral-home leads into the crawl queue."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    count = import_manual_leads(args.input, args.output)
    print(f"Imported {count} unique leads into {args.output}")


if __name__ == "__main__":
    main()
