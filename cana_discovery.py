#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

from discovery.providers.cana import CanaDirectoryClient


DEFAULT_OUTPUT = Path("data/discovery_sources/cana.json")


def export_cana_directory(
    output_path: Path, countries=("Canada",), timeout=30, delay=0.5, retries=2,
    target_only=True,
):
    records = CanaDirectoryClient(
        timeout=timeout, delay=delay, retries=retries
    ).fetch(countries, target_only=target_only)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )
    temporary.replace(output_path)
    return len(records)


def main():
    parser = argparse.ArgumentParser(description="Export public CANA member records.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--country", action="append", dest="countries",
        help="Repeat for Canada and/or United States; defaults to Canada.",
    )
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--retries", type=int, choices=range(0, 6), default=2)
    parser.add_argument(
        "--include-other-members", action="store_true",
        help="Include CANA records not categorized as a funeral home, mortuary, or crematory.",
    )
    args = parser.parse_args()
    countries = tuple(args.countries or ["Canada"])
    allowed = {"Canada", "United States"}
    if any(country not in allowed for country in countries):
        parser.error("--country must be Canada or United States")
    count = export_cana_directory(
        args.output, countries, args.timeout, args.delay, args.retries,
        target_only=not args.include_other_members,
    )
    print(f"Exported {count} CANA member locations into {args.output}")


if __name__ == "__main__":
    main()
