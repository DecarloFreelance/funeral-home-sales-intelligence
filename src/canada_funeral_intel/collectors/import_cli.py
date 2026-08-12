from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from canada_funeral_intel.collectors.import_execution import import_file
from canada_funeral_intel.collectors.importers import ImportFormat, ImportFrameworkError
from canada_funeral_intel.collectors.source_registry import load_source_registry
from canada_funeral_intel.collectors.source_registry_storage import seed_source_registry
from canada_funeral_intel.storage.migrations import apply_pending_migrations


class ImportCommandError(RuntimeError):
    """Raised when a CLI import cannot be completed."""


def run_import_command(
    connection: sqlite3.Connection,
    *,
    migration_dir: Path,
    registry_path: Path,
    source_name: str,
    input_path: Path,
    input_format: ImportFormat,
    external_id_field: str | None,
) -> dict[str, object]:
    try:
        apply_pending_migrations(connection, migration_dir)

        registry = load_source_registry(registry_path)
        seed_source_registry(connection, registry)
        connection.commit()

        requested = source_name.casefold()
        definition = next(
            (source for source in registry if source.name.casefold() == requested),
            None,
        )
        if definition is None:
            raise ImportCommandError(f"Source not found: {source_name}")

        row = connection.execute(
            "SELECT id FROM source_datasets WHERE name = ?",
            (definition.name,),
        ).fetchone()
        if row is None:
            raise ImportCommandError(
                f"Source registry seed failed for: {definition.name}"
            )

        result = import_file(
            connection,
            source_dataset_id=int(row["id"]),
            input_path=input_path,
            input_format=input_format,
            external_id_field=external_id_field,
            source_url=definition.source_url,
        )
    except ImportCommandError:
        raise
    except (ImportFrameworkError, sqlite3.Error, ValueError) as exc:
        raise ImportCommandError(str(exc)) from exc

    return {
        "import_run_id": result.import_run_id,
        "source": definition.name,
        "input_path": str(input_path),
        "input_format": input_format.value,
        "records_seen": result.records_seen,
        "records_inserted": result.records_inserted,
        "records_unchanged": result.records_unchanged,
        "records_failed": result.records_failed,
    }


def print_import_result(payload: dict[str, object]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))
