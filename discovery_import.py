#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

from discovery.ingestion import build_crawl_queue
from discovery.source_adapters import load_source, parse_source_spec


DEFAULT_OUTPUT = Path("data/crawl_queue.json")


def import_discovery_sources(source_specs, output_path: Path) -> int:
    leads = []
    for spec in source_specs:
        source, path = parse_source_spec(spec)
        leads.extend(load_source(path, source))

    queue = build_crawl_queue(leads)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(queue, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output_path)
    return len(queue)


def main():
    parser = argparse.ArgumentParser(
        description="Merge discovery-source exports into the normalized crawl queue."
    )
    parser.add_argument(
        "--source",
        action="append",
        dest="sources",
        metavar="TYPE=PATH",
        help="Repeat for manual, maps, search, association, or directory exports.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    sources = args.sources or ["manual=data/seeds/manual_leads.csv"]
    count = import_discovery_sources(sources, args.output)
    print(f"Imported {count} unique leads into {args.output}")


if __name__ == "__main__":
    main()
