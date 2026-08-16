from __future__ import annotations

import sqlite3
from pathlib import Path

from canada_funeral_intel.collectors.import_execution import import_parsed_records
from canada_funeral_intel.collectors.importers import ImportFormat
from canada_funeral_intel.collectors.saskatchewan import (
    SASKATCHEWAN_ROSTER_URL,
    SASKATCHEWAN_SOURCE_NAME,
    collect_parse_result,
)
from canada_funeral_intel.collectors.source_registry import load_source_registry
from canada_funeral_intel.collectors.source_registry_storage import seed_source_registry
from canada_funeral_intel.storage.migrations import apply_pending_migrations


class SaskatchewanCollectCommandError(RuntimeError):
    """Raised when the Saskatchewan source collection command fails."""


def run_saskatchewan_collect_command(
    connection: sqlite3.Connection,
    *,
    migration_dir: Path,
    registry_path: Path,
    source_name: str = SASKATCHEWAN_SOURCE_NAME,
    user_agent: str = "CanadaFuneralIntel/0.1",
    timeout_seconds: float = 20.0,
) -> dict[str, object]:
    try:
        apply_pending_migrations(connection, migration_dir)
        registry = load_source_registry(registry_path)
        seed_source_registry(connection, registry)
        connection.commit()
        definition = next(
            (
                source
                for source in registry
                if source.name.casefold() == source_name.casefold()
            ),
            None,
        )
        if definition is None or definition.name != SASKATCHEWAN_SOURCE_NAME:
            raise SaskatchewanCollectCommandError(
                f"Live collection is not implemented for source: {source_name}"
            )
        dataset = connection.execute(
            "SELECT id FROM source_datasets WHERE name = ?", (definition.name,)
        ).fetchone()
        if dataset is None:
            raise SaskatchewanCollectCommandError(
                "Source registry seed failed for Saskatchewan"
            )
        parsed = collect_parse_result(
            user_agent=user_agent, timeout_seconds=timeout_seconds
        )
        result = import_parsed_records(
            connection,
            source_dataset_id=int(dataset["id"]),
            input_path=Path("remote/saskatchewan/roster.pdf"),
            input_format=ImportFormat.JSON,
            parsed=parsed,
            source_url=SASKATCHEWAN_ROSTER_URL,
        )
    except SaskatchewanCollectCommandError:
        raise
    except Exception as exc:
        raise SaskatchewanCollectCommandError(str(exc)) from exc
    return {
        "import_run_id": result.import_run_id,
        "source": definition.name,
        "source_url": SASKATCHEWAN_ROSTER_URL,
        "records_seen": result.records_seen,
        "records_inserted": result.records_inserted,
        "records_unchanged": result.records_unchanged,
        "records_failed": result.records_failed,
    }
