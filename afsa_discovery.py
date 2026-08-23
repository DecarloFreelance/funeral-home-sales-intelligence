#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

from discovery.providers.afsa import AfsaDirectoryClient


DEFAULT_OUTPUT = Path("data/discovery_sources/afsa.json")


def export_afsa_directory(output_path: Path, timeout=20, delay=0.5) -> int:
    records = AfsaDirectoryClient(timeout=timeout, delay=delay).fetch()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(records, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output_path)
    return len(records)


def main():
    parser = argparse.ArgumentParser(
        description="Export public AFSA funeral-provider directory records."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--delay", type=float, default=0.5)
    args = parser.parse_args()

    count = export_afsa_directory(args.output, args.timeout, args.delay)
    print(f"Exported {count} AFSA member locations into {args.output}")


if __name__ == "__main__":
    main()
