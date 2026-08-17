from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from canada_funeral_intel.collectors.importers import ImportFormat
from canada_funeral_intel.collectors.source_registry import load_source_registry
from canada_funeral_intel.collectors.source_registry_storage import seed_source_registry
from canada_funeral_intel.pipeline import orchestrator
from canada_funeral_intel.pipeline.orchestrator import (
    PipelineError,
    PipelineInput,
    create_run,
    resume_run,
)
from canada_funeral_intel.storage import database_session
from canada_funeral_intel.storage.migrations import apply_pending_migrations

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "database" / "migrations"
REGISTRY = ROOT / "config" / "sources.json"


def _database(path: Path) -> tuple[Path, int]:
    with database_session(path) as connection:
        assert (
            apply_pending_migrations(connection, MIGRATIONS).status.current_version
        == 27
        )
        seed_source_registry(connection, load_source_registry(REGISTRY))
        connection.commit()
        row = connection.execute(
            "SELECT id FROM source_datasets WHERE name = ?",
            ("Manual Canadian Funeral Home Source",),
        ).fetchone()
    assert row is not None
    return path, int(row["id"])


def _input(path: Path, *, changed: bool = False) -> Path:
    value = "Alpha Updated" if changed else "Alpha"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "a",
                    "name": value,
                    "city": "Calgary",
                    "province": "AB",
                    "phone": "403-555-0100",
                    "postal_code": "T2P1J9",
                }
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_pipeline_runs_end_to_end_and_identical_rerun_is_idempotent(
    tmp_path: Path,
) -> None:
    database_path, dataset_id = _database(tmp_path / "pipeline.sqlite3")
    input_path = _input(tmp_path / "records.json")
    spec = PipelineInput(dataset_id, input_path, ImportFormat.JSON, "id")

    with database_session(database_path) as connection:
        first = create_run(connection, spec)
        first_counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "source_records",
                "normalized_values",
                "entities",
                "entity_source_records",
                "pipeline_run_stages",
            )
        }
        second = create_run(connection, spec)
        second_counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "source_records",
                "normalized_values",
                "entities",
                "entity_source_records",
            )
        }

    assert first["status"] == "completed"
    assert all(stage["status"] == "completed" for stage in first["stages"])
    assert second["status"] == "completed"
    assert second_counts == {
        key: value
        for key, value in first_counts.items()
        if key != "pipeline_run_stages"
    }


def test_dry_run_does_not_persist_or_mutate_domain(tmp_path: Path) -> None:
    database_path, dataset_id = _database(tmp_path / "dry.sqlite3")
    input_path = _input(tmp_path / "records.json")
    spec = PipelineInput(dataset_id, input_path, ImportFormat.JSON, "id")
    with database_session(database_path) as connection:
        before = connection.execute("SELECT COUNT(*) FROM source_records").fetchone()[0]
        result = create_run(connection, spec, dry_run=True)
        after = connection.execute("SELECT COUNT(*) FROM source_records").fetchone()[0]
        runs = connection.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()[0]
    assert result["dry_run"] is True
    assert result["run_id"] is None
    assert before == after == 0
    assert runs == 0


def test_failed_stage_is_persisted_and_resume_rejects_changed_input(
    tmp_path: Path,
) -> None:
    database_path, dataset_id = _database(tmp_path / "failure.sqlite3")
    input_path = _input(tmp_path / "records.json")
    input_path.write_text("not-json", encoding="utf-8")
    with database_session(database_path) as connection:
        with pytest.raises(PipelineError, match="Invalid JSON"):
            create_run(
                connection,
                PipelineInput(
                    dataset_id,
                    input_path,
                    ImportFormat.JSON,
                    "id",
                    through_stage="import",
                ),
            )
        row = connection.execute("SELECT id, status FROM pipeline_runs").fetchone()
        assert row["status"] == "failed"
        error = connection.execute("SELECT id FROM pipeline_run_errors").fetchone()
        assert error is not None
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE pipeline_run_errors SET error_message = 'changed' WHERE id = ?",
                (error["id"],),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "DELETE FROM pipeline_run_errors WHERE id = ?", (error["id"],)
            )
        input_path.write_text(
            json.dumps([{"id": "a", "name": "Alpha"}]), encoding="utf-8"
        )
        with pytest.raises(PipelineError, match="changed"):
            resume_run(connection, int(row["id"]))


def test_resume_claim_prevents_running_run_reuse(tmp_path: Path) -> None:
    database_path, dataset_id = _database(tmp_path / "resume.sqlite3")
    input_path = _input(tmp_path / "records.json")
    with database_session(database_path) as connection:
        result = create_run(
            connection,
            PipelineInput(
                dataset_id, input_path, ImportFormat.JSON, "id", through_stage="import"
            ),
        )
        run_id = int(result["id"])
        connection.execute(
            "UPDATE pipeline_runs SET status = 'running' WHERE id = ?", (run_id,)
        )
        connection.commit()
        with pytest.raises(PipelineError, match="cannot be resumed"):
            resume_run(connection, run_id)


def test_resume_skips_completed_stages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path, dataset_id = _database(tmp_path / "resume-stage.sqlite3")
    input_path = _input(tmp_path / "records.json")
    original = orchestrator._execute_stage
    failed_once = {"value": False}

    def fail_review(connection, stage, spec):
        if stage == "review_queue" and not failed_once["value"]:
            failed_once["value"] = True
            raise PipelineError("fixture review failure")
        return original(connection, stage, spec)

    monkeypatch.setattr(orchestrator, "_execute_stage", fail_review)
    with database_session(database_path) as connection:
        with pytest.raises(PipelineError, match="fixture review failure"):
            create_run(
                connection,
                PipelineInput(dataset_id, input_path, ImportFormat.JSON, "id"),
            )
        run_id = int(connection.execute("SELECT id FROM pipeline_runs").fetchone()[0])
        completed_before = connection.execute(
            "SELECT stage_name FROM pipeline_run_stages WHERE pipeline_run_id=? AND status='completed' ORDER BY ordinal",
            (run_id,),
        ).fetchall()
        assert [row["stage_name"] for row in completed_before] == [
            "import",
            "normalize",
            "deterministic_match",
            "fuzzy_match",
        ]
        result = resume_run(connection, run_id)
    assert result["status"] == "completed"
    assert result["stages"][0]["attempt_count"] == 1
    assert result["stages"][4]["attempt_count"] == 2
