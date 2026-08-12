from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from canada_funeral_intel.collectors.source_registry import (
    SourceRegistryError,
    load_source_registry,
)
from canada_funeral_intel.collectors.source_registry_storage import seed_source_registry
from canada_funeral_intel.normalization.execution import (
    NormalizationExecutionError,
    normalize_source_records,
)
from canada_funeral_intel.storage.migrations import apply_pending_migrations


class NormalizeCommandError(RuntimeError):
    """Raised when a CLI normalization run cannot be completed."""


def run_normalize_command(
    connection: sqlite3.Connection,
    *,
    migration_dir: Path,
    registry_path: Path,
    source_name: str | None,
) -> dict[str, object]:
    try:
        apply_pending_migrations(connection, migration_dir)

        registry = load_source_registry(registry_path)
        seed_source_registry(connection, registry)
        connection.commit()

        source_dataset_id: int | None = None
        resolved_source: str | None = None

        if source_name is not None:
            requested = source_name.casefold()
            definition = next(
                (source for source in registry if source.name.casefold() == requested),
                None,
            )
            if definition is None:
                raise NormalizeCommandError(f"Source not found: {source_name}")

            row = connection.execute(
                "SELECT id FROM source_datasets WHERE name = ?",
                (definition.name,),
            ).fetchone()
            if row is None:
                raise NormalizeCommandError(
                    f"Source registry seed failed for: {definition.name}"
                )

            source_dataset_id = int(row["id"])
            resolved_source = definition.name

        result = normalize_source_records(
            connection,
            source_dataset_id=source_dataset_id,
        )
    except NormalizeCommandError:
        raise
    except (
        NormalizationExecutionError,
        SourceRegistryError,
        sqlite3.Error,
        ValueError,
    ) as exc:
        raise NormalizeCommandError(str(exc)) from exc

    return {
        "source": resolved_source,
        "source_dataset_id": source_dataset_id,
        "records_seen": result.records_seen,
        "values_inserted": result.values_inserted,
        "values_unchanged": result.values_unchanged,
        "fields_skipped": result.fields_skipped,
    }


def print_normalize_result(payload: dict[str, object]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))
