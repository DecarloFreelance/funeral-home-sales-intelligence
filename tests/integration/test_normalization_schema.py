from pathlib import Path

from canada_funeral_intel.storage import database_session
from canada_funeral_intel.storage.migrations import apply_pending_migrations

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "database" / "migrations"


def test_normalization_provenance_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "normalization.sqlite3"

    with database_session(database_path) as connection:
        status = apply_pending_migrations(connection, MIGRATIONS).status

        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(normalized_values)")
        }
        indexes = {
            row["name"]
            for row in connection.execute("PRAGMA index_list(normalized_values)")
        }

    assert status.current_version == 21
    assert {
        "source_record_id",
        "field_name",
        "original_value",
        "normalized_value",
        "normalizer_name",
        "normalizer_version",
        "normalized_at",
        "warnings",
    } <= columns
    assert {
        "idx_normalized_values_source_record",
        "idx_normalized_values_field",
        "idx_normalized_values_normalizer",
        "idx_normalized_values_source_field",
    } <= indexes
