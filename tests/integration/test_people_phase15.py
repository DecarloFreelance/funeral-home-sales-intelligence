from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from canada_funeral_intel.people.dispositions import (
    DispositionStatus,
    decide_disposition,
)
from canada_funeral_intel.people.remediation import (
    RemediationStatus,
    create_task,
    update_task,
)
from canada_funeral_intel.people.work_queue import (
    WorkQueueFilters,
    export_work_queue_csv,
    list_work_queue,
    owner_workload,
    show_work_item,
)
from canada_funeral_intel.storage.database import database_session
from canada_funeral_intel.storage.migrations import apply_pending_migrations
from tests.integration.test_people_merge_phase10 import _fixture
from tests.integration.test_people_phase13 import _open_anomaly

MIGRATIONS = Path(__file__).resolve().parents[2] / "database" / "migrations"
REFERENCE = datetime(2026, 8, 12, 12, tzinfo=UTC)


def test_queue_binds_exact_fingerprint_and_priority_is_deterministic(tmp_path: Path) -> None:
    with database_session(tmp_path / "queue.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        person_id, _, _, _, _ = _fixture(connection)
        anomaly = _open_anomaly(connection, person_id)
        first = list_work_queue(connection, WorkQueueFilters(person_id=person_id, reference_time=REFERENCE))
        assert len(first) == 1
        row = first[0]
        assert row["anomaly_fingerprint"] == anomaly["fingerprint"]
        assert row["queue_state"] == "unreviewed"
        assert row["computed_priority"] == 340
        assert row["priority_reasons"] == ["unreviewed"]
        decide_disposition(connection, person_id=person_id, anomaly_code=anomaly["code"], fingerprint=anomaly["fingerprint"], status=DispositionStatus.ACKNOWLEDGED, actor="alex")
        create_task(connection, person_id=person_id, anomaly_code=anomaly["code"], fingerprint=anomaly["fingerprint"], task_type="verify_identity", actor="alex", owner="alex", due_at="2026-08-12T11:00:00Z")
        current = list_work_queue(connection, WorkQueueFilters(person_id=person_id, reference_time=REFERENCE))[0]
        assert current["queue_state"] == "remediation_overdue"
        assert current["computed_priority"] == 390
        assert show_work_item(connection, person_id=person_id, fingerprint=anomaly["fingerprint"], reference_time=REFERENCE)["person_id"] == person_id


def test_task_states_filters_owner_and_export_are_deterministic(tmp_path: Path) -> None:
    with database_session(tmp_path / "filters.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        person_id, _, _, _, _ = _fixture(connection)
        anomaly = _open_anomaly(connection, person_id)
        task = create_task(connection, person_id=person_id, anomaly_code=anomaly["code"], fingerprint=anomaly["fingerprint"], task_type="inspect_source", actor="alex", owner="alex", due_at="2026-08-20T12:00:00Z")
        assert list_work_queue(connection, WorkQueueFilters(has_remediation=True, reference_time=REFERENCE))[0]["person_id"] == person_id
        assert list_work_queue(connection, WorkQueueFilters(owner="alex", reference_time=REFERENCE))[0]["person_id"] == person_id
        assert list_work_queue(connection, WorkQueueFilters(unassigned_only=True, anomaly=anomaly["code"], reference_time=REFERENCE)) == []
        update_task(connection, task_id=task.task_id, actor="alex", status=RemediationStatus.BLOCKED)
        blocked = list_work_queue(connection, WorkQueueFilters(blocked_only=True, reference_time=REFERENCE))[0]
        assert blocked["queue_state"] == "remediation_blocked"
        owners = owner_workload(connection, reference_time=REFERENCE)
        assert owners[0]["owner"] == "alex"
        first, second = tmp_path / "one", tmp_path / "two"
        export_work_queue_csv(connection, first, reference_time=REFERENCE)
        export_work_queue_csv(connection, second, reference_time=REFERENCE)
        assert (first / "person_work_queue.csv").read_bytes() == (second / "person_work_queue.csv").read_bytes()
        assert (first / "person_work_queue_owners.csv").read_bytes() == (second / "person_work_queue_owners.csv").read_bytes()


def test_work_queue_projection_is_read_only(tmp_path: Path) -> None:
    with database_session(tmp_path / "readonly.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        person_id, _, _, _, _ = _fixture(connection)
        anomaly = _open_anomaly(connection, person_id)
        create_task(connection, person_id=person_id, anomaly_code=anomaly["code"], fingerprint=anomaly["fingerprint"], task_type="other", actor="alex")
        before = {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("people", "person_affiliations", "person_contact_points", "person_evidence", "person_anomaly_dispositions", "person_anomaly_disposition_history", "person_anomaly_remediation_tasks", "person_anomaly_remediation_task_history")}
        total_changes = connection.total_changes
        list_work_queue(connection, WorkQueueFilters(reference_time=REFERENCE))
        show_work_item(connection, person_id=person_id, fingerprint=anomaly["fingerprint"], reference_time=REFERENCE)
        owner_workload(connection, reference_time=REFERENCE)
        export_work_queue_csv(connection, tmp_path / "export", reference_time=REFERENCE)
        after = {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in before}
        assert after == before
        assert connection.total_changes == total_changes
