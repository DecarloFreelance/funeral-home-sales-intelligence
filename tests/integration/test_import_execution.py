from __future__ import annotations

import json
from pathlib import Path

import pytest

from canada_funeral_intel.collectors.import_execution import (
    import_file,
    import_parsed_records,
)
from canada_funeral_intel.collectors.importers import (
    ImportFormat,
    ImportFrameworkError,
    parse_json,
)
from canada_funeral_intel.collectors.source_registry import load_source_registry
from canada_funeral_intel.collectors.source_registry_storage import seed_source_registry
from canada_funeral_intel.storage import database_session
from canada_funeral_intel.storage.migrations import apply_pending_migrations

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "database" / "migrations"
REGISTRY = ROOT / "config" / "sources.json"


def prepared_database(path: Path) -> int:
    with database_session(path) as connection:
        status = apply_pending_migrations(connection, MIGRATIONS).status
        seed_source_registry(connection, load_source_registry(REGISTRY))
        connection.commit()
        row = connection.execute(
            "SELECT id FROM source_datasets WHERE name = ?",
            ("Manual Canadian Funeral Home Source",),
        ).fetchone()
    assert status.current_version == 20
    assert row is not None
    return int(row["id"])


def test_import_file_and_unchanged_detection(tmp_path: Path) -> None:
    database_path = tmp_path / "import.sqlite3"
    dataset_id = prepared_database(database_path)
    input_path = tmp_path / "records.json"
    input_path.write_text(
        '[{"id":"1","name":"Alpha"},{"id":"2","name":"Beta"}]',
        encoding="utf-8",
    )

    with database_session(database_path) as connection:
        first = import_file(
            connection,
            source_dataset_id=dataset_id,
            input_path=input_path,
            input_format=ImportFormat.JSON,
            external_id_field="id",
        )
        second = import_file(
            connection,
            source_dataset_id=dataset_id,
            input_path=input_path,
            input_format=ImportFormat.JSON,
            external_id_field="id",
        )
        count = connection.execute("SELECT COUNT(*) FROM source_records").fetchone()[0]

    assert first.records_seen == 2
    assert first.records_inserted == 2
    assert second.records_inserted == 0
    assert second.records_unchanged == 2
    assert count == 2


def test_changed_external_record_preserves_history(tmp_path: Path) -> None:
    database_path = tmp_path / "import.sqlite3"
    dataset_id = prepared_database(database_path)
    input_path = tmp_path / "records.json"

    input_path.write_text('[{"id":"1","name":"Alpha"}]', encoding="utf-8")

    with database_session(database_path) as connection:
        import_file(
            connection,
            source_dataset_id=dataset_id,
            input_path=input_path,
            input_format=ImportFormat.JSON,
            external_id_field="id",
        )
        input_path.write_text(
            '[{"id":"1","name":"Alpha Updated"}]',
            encoding="utf-8",
        )
        result = import_file(
            connection,
            source_dataset_id=dataset_id,
            input_path=input_path,
            input_format=ImportFormat.JSON,
            external_id_field="id",
        )
        rows = connection.execute(
            "SELECT raw_payload FROM source_records ORDER BY id"
        ).fetchall()

    assert result.records_inserted == 1
    assert len(rows) == 2
    assert json.loads(rows[0]["raw_payload"])["name"] == "Alpha"
    assert json.loads(rows[1]["raw_payload"])["name"] == "Alpha Updated"


def test_row_errors_are_persisted(tmp_path: Path) -> None:
    database_path = tmp_path / "import.sqlite3"
    dataset_id = prepared_database(database_path)
    parsed = parse_json(
        '[{"id":"ok","name":"Alpha"},42,{"id":{"bad":1},"name":"Bad"}]',
        external_id_field="id",
    )

    with database_session(database_path) as connection:
        result = import_parsed_records(
            connection,
            source_dataset_id=dataset_id,
            input_path=tmp_path / "errors.json",
            input_format=ImportFormat.JSON,
            parsed=parsed,
        )
        errors = connection.execute(
            "SELECT row_number, error_message FROM import_run_errors "
            "WHERE import_run_id = ? ORDER BY row_number",
            (result.import_run_id,),
        ).fetchall()
        run = connection.execute(
            "SELECT * FROM import_runs WHERE id = ?",
            (result.import_run_id,),
        ).fetchone()

    assert result.records_seen == 3
    assert result.records_inserted == 1
    assert result.records_failed == 2
    assert [row["row_number"] for row in errors] == [2, 3]
    assert run is not None
    assert run["status"] == "completed"
    assert run["records_failed"] == 2


def test_database_error_rolls_back_entire_import(tmp_path: Path) -> None:
    database_path = tmp_path / "import.sqlite3"
    dataset_id = prepared_database(database_path)
    parsed = parse_json(
        '[{"id":"1","name":"Alpha"}]',
        external_id_field="id",
    )

    with database_session(database_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_source_record_insert
            BEFORE INSERT ON source_records
            BEGIN
                SELECT RAISE(ABORT, 'forced failure');
            END
            """
        )
        connection.commit()

        with pytest.raises(ImportFrameworkError, match="Database import failed"):
            import_parsed_records(
                connection,
                source_dataset_id=dataset_id,
                input_path=tmp_path / "records.json",
                input_format=ImportFormat.JSON,
                parsed=parsed,
            )

        runs = connection.execute("SELECT COUNT(*) FROM import_runs").fetchone()[0]
        records = connection.execute("SELECT COUNT(*) FROM source_records").fetchone()[
            0
        ]

    assert runs == 0
    assert records == 0
