from __future__ import annotations

import sqlite3
from pathlib import Path

from canada_funeral_intel.collectors.importers import ImportFormat

from .orchestrator import (
    PipelineInput,
    create_run,
    list_runs,
    list_stages,
    resume_run,
    show_run,
)


def resolve_source_dataset(connection: sqlite3.Connection, source_name: str) -> int:
    row = connection.execute("SELECT id FROM source_datasets WHERE lower(name) = lower(?)", (source_name,)).fetchone()
    if row is None:
        raise ValueError(f"Source dataset not found: {source_name}")
    return int(row["id"])


def run_pipeline(connection: sqlite3.Connection, *, source_name: str, input_path: Path, input_format: ImportFormat, external_id_field: str | None, through_stage: str, skip_fuzzy: bool, dry_run: bool = False) -> dict[str, object]:
    dataset_id = resolve_source_dataset(connection, source_name)
    return create_run(connection, PipelineInput(dataset_id, input_path, input_format, external_id_field, through_stage, skip_fuzzy), dry_run=dry_run)


def run_pipeline_resume(connection: sqlite3.Connection, run_id: int) -> dict[str, object]:
    return resume_run(connection, run_id)


def run_pipeline_show(connection: sqlite3.Connection, run_id: int) -> dict[str, object]:
    return show_run(connection, run_id)


def run_pipeline_list(connection: sqlite3.Connection, *, status: str | None = None, limit: int | None = None) -> list[dict[str, object]]:
    return list_runs(connection, status=status, limit=limit)


def run_pipeline_stages(connection: sqlite3.Connection, run_id: int) -> list[dict[str, object]]:
    return list_stages(connection, run_id)
