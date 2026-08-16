from __future__ import annotations

import argparse
import json
from pathlib import Path

from canada_funeral_intel.reporting.public_directory import write_public_directory


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the curated static public directory snapshot."
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("database/sqlite/funeral_homes.sqlite3"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("site/data/directory.json"),
    )
    args = parser.parse_args()
    payload = write_public_directory(args.database, args.output)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "directory_version": payload["directory_version"],
                "record_count": payload["record_count"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
