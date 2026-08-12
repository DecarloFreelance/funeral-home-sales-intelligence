#!/usr/bin/env python3
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from canada_funeral_intel.collectors.import_execution import import_file
from canada_funeral_intel.collectors.importers import ImportFormat
from canada_funeral_intel.storage.database import database_session


def main():
    # Get database connection using database_session
    with database_session("database/sqlite/funeral_homes.sqlite3") as conn:
        # Import CSV
        result = import_file(
            connection=conn,
            source_dataset_id=1,
            input_path=Path("data/raw/sample.csv"),
            input_format=ImportFormat.CSV,
            external_id_field="external_id",
            source_url="file://data/raw/sample.csv",
        )

        print("Import Result:")
        print(f"  Records seen: {result.records_seen}")
        print(f"  Records inserted: {result.records_inserted}")
        print(f"  Records unchanged: {result.records_unchanged}")
        print(f"  Records failed: {result.records_failed}")


if __name__ == "__main__":
    main()
