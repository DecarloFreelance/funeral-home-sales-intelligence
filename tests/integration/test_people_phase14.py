from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from canada_funeral_intel.people.audit import audit_person, export_people_csv
from canada_funeral_intel.people.models import PersonResolutionError
from canada_funeral_intel.people.remediation import (
    RemediationStatus,
    create_task,
    list_tasks,
    show_task,
    sync_tasks,
    task_history,
    update_task,
)
from canada_funeral_intel.people.triage import TriageFilters, triage_people
from canada_funeral_intel.storage.database import database_session
from canada_funeral_intel.storage.migrations import apply_pending_migrations
from tests.integration.test_people_merge_phase10 import _fixture
from tests.integration.test_people_phase13 import _open_anomaly

MIGRATIONS = Path(__file__).resolve().parents[2] / "database" / "migrations"


def test_task_lifecycle_and_exact_fingerprint_binding(tmp_path: Path) -> None:
    with database_session(tmp_path / "tasks.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        person_id, _, _, _, _ = _fixture(connection)
        anomaly = _open_anomaly(connection, person_id)
        task = create_task(connection, person_id=person_id, anomaly_code=anomaly["code"], fingerprint=anomaly["fingerprint"], task_type="verify_contact", actor="alex", owner="alex", due_at="2026-08-20T17:00:00Z", note="confirm")
        assert task.status is RemediationStatus.OPEN
        assert update_task(connection, task_id=task.task_id, actor="alex", status=RemediationStatus.IN_PROGRESS).status is RemediationStatus.IN_PROGRESS
        assert update_task(connection, task_id=task.task_id, actor="alex", status=RemediationStatus.BLOCKED).status is RemediationStatus.BLOCKED
        assert update_task(connection, task_id=task.task_id, actor="alex", status=RemediationStatus.IN_PROGRESS, clear_owner=True, clear_due_at=True).status is RemediationStatus.IN_PROGRESS
        assert update_task(connection, task_id=task.task_id, actor="alex", status=RemediationStatus.COMPLETED).status is RemediationStatus.COMPLETED
        assert update_task(connection, task_id=task.task_id, actor="alex", status=RemediationStatus.COMPLETED).changed is False
        assert connection.execute("SELECT owner, due_at FROM person_anomaly_remediation_tasks WHERE id = ?", (task.task_id,)).fetchone()[:2] == (None, None)
        assert len(task_history(connection, task.task_id)) == 5
        with pytest.raises(PersonResolutionError):
            create_task(connection, person_id=person_id, anomaly_code=anomaly["code"], fingerprint="wrong", task_type="other", actor="alex")
        with pytest.raises(PersonResolutionError):
            create_task(connection, person_id=person_id, anomaly_code=anomaly["code"], fingerprint=anomaly["fingerprint"], task_type="other", actor=" ")
        with pytest.raises(PersonResolutionError):
            update_task(connection, task_id=task.task_id, actor="alex", status=RemediationStatus.STALE)


def test_task_summary_filters_overdue_and_audit_are_read_only(tmp_path: Path) -> None:
    with database_session(tmp_path / "summary.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        person_id, _, _, _, _ = _fixture(connection)
        anomaly = _open_anomaly(connection, person_id)
        before = {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("people", "person_evidence", "person_anomaly_dispositions")}
        task = create_task(connection, person_id=person_id, anomaly_code=anomaly["code"], fingerprint=anomaly["fingerprint"], task_type="inspect_source", actor="alex", owner="alex", due_at="2020-01-01T00:00:00Z")
        triage = triage_people(connection, TriageFilters(person_id=person_id))[0]
        item = triage["anomalies"][0]
        assert item["remediation"]["remediation_task_ids"] == [task.task_id]
        assert triage_people(connection, TriageFilters(has_remediation=True))[0]["person_id"] == person_id
        assert triage_people(connection, TriageFilters(no_remediation=True, anomaly=anomaly["code"])) == []
        assert triage_people(connection, TriageFilters(overdue_remediation=True))[0]["person_id"] == person_id
        assert list_tasks(connection, overdue_only=True, now="2021-01-01T00:00:00Z")[0]["id"] == task.task_id
        assert show_task(connection, task.task_id)["current_anomaly"] is True
        audit = audit_person(connection, person_id)
        assert audit["person"]["person_id"] == person_id
        after = {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in before}
        assert after == {**before, "person_evidence": before["person_evidence"]}


def test_sync_stales_task_without_creating_new_task(tmp_path: Path) -> None:
    with database_session(tmp_path / "sync.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        person_id, _, _, _, _ = _fixture(connection)
        anomaly = _open_anomaly(connection, person_id)
        task = create_task(connection, person_id=person_id, anomaly_code=anomaly["code"], fingerprint=anomaly["fingerprint"], task_type="other", actor="alex")
        connection.execute("INSERT INTO person_evidence (person_id, observation_id, review_decision) SELECT ?, observation_id, 'accepted' FROM person_observation_review_queue LIMIT 1", (person_id,))
        connection.commit()
        assert sync_tasks(connection, person_id=person_id)["marked_stale"] == 1
        assert sync_tasks(connection, person_id=person_id)["marked_stale"] == 0
        stored = list_tasks(connection, person_id=person_id, include_stale=True)
        assert stored[0]["status"] == "stale"
        assert len(task_history(connection, task.task_id)) == 2
        assert triage_people(connection, TriageFilters(person_id=person_id))[0]["anomalies"] == []


def test_history_is_immutable_and_exports_repeatably(tmp_path: Path) -> None:
    with database_session(tmp_path / "export.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        person_id, _, _, _, _ = _fixture(connection)
        anomaly = _open_anomaly(connection, person_id)
        task = create_task(connection, person_id=person_id, anomaly_code=anomaly["code"], fingerprint=anomaly["fingerprint"], task_type="other", actor="alex")
        history_id = task_history(connection, task.task_id)[0]["id"]
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE person_anomaly_remediation_task_history SET note = 'tamper' WHERE id = ?", (history_id,))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM person_anomaly_remediation_task_history WHERE id = ?", (history_id,))
        first, second = tmp_path / "one", tmp_path / "two"
        export_people_csv(connection, first)
        export_people_csv(connection, second)
        for path in first.glob("*.csv"):
            assert path.read_bytes() == (second / path.name).read_bytes()
