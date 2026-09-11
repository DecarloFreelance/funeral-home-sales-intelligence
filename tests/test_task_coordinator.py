import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from automation.task_coordinator import TaskCoordinator


def manifest(path):
    path.write_text(json.dumps({
        "schema_version": 2,
        "tasks": [
            {
                "id": "TASK-A", "task_version": 1, "title": "Active task",
                "owner": None, "declared_status": "ACTIVE", "depends_on": [],
                "requires_review": True, "audit_refs": [],
            },
            {
                "id": "TASK-B", "task_version": 2, "title": "Dependent task",
                "owner": None, "declared_status": "ACTIVE", "depends_on": ["TASK-A"],
                "requires_review": False, "audit_refs": [],
            },
            {
                "id": "TASK-BLOCKED", "task_version": 1, "title": "Blocked task",
                "owner": None, "declared_status": "BLOCKED", "depends_on": [],
                "requires_review": True, "audit_refs": ["AUDIT-1"],
            },
        ],
    }), encoding="utf-8")


def coordinator(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest(manifest_path)
    return TaskCoordinator(manifest_path, tmp_path / "state.json")


def test_ready_claim_and_completion_are_review_only(tmp_path):
    runner = coordinator(tmp_path)
    assert [task["id"] for task in runner.list_ready_tasks()] == ["TASK-A"]
    claim = runner.claim_task("TASK-A", "worker-1", 1, "input-a")
    assert claim["lease"]["worker_id"] == "worker-1"
    with pytest.raises(ValueError, match="already claimed"):
        runner.claim_task("TASK-A", "worker-2", 1, "input-a")

    completion = runner.reconcile_completion("TASK-A", "worker-1", {
        "task_version": 1, "input_fingerprint": "input-a",
        "completion_fingerprint": "output-a", "outcome": "REVIEW",
        "review_status": "REVIEW", "audit_id": "audit-a",
    })
    assert completion["execution_status"] == "COMPLETED"
    assert completion["review_status"] == "REVIEW"
    assert runner.reconcile_completion("TASK-A", "worker-1", {
        "task_version": 1, "input_fingerprint": "input-a",
        "completion_fingerprint": "output-a", "outcome": "REVIEW",
        "review_status": "REVIEW", "audit_id": "audit-a",
    }) == completion
    assert [task["id"] for task in runner.list_ready_tasks()] == ["TASK-B"]


def test_stale_version_and_mismatched_completion_are_rejected(tmp_path):
    runner = coordinator(tmp_path)
    with pytest.raises(ValueError, match="version"):
        runner.claim_task("TASK-A", "worker-1", 99, "input-a")
    runner.claim_task("TASK-A", "worker-1", 1, "input-a")
    with pytest.raises(ValueError, match="fingerprint"):
        runner.reconcile_completion("TASK-A", "worker-1", {
            "task_version": 1, "input_fingerprint": "other",
            "completion_fingerprint": "output-a", "outcome": "REVIEW",
        })
    with pytest.raises(ValueError, match="worker"):
        runner.renew_lease("TASK-A", "worker-2", 1)


def test_expired_lease_recovers_and_contradictory_state_is_rejected(tmp_path):
    runner = coordinator(tmp_path)
    runner.claim_task("TASK-A", "worker-1", 1, "input-a")
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    state["tasks"]["TASK-A"]["lease"]["expires_at"] = "2000-01-01T00:00:00Z"
    (tmp_path / "state.json").write_text(json.dumps(state), encoding="utf-8")
    recovered = TaskCoordinator(tmp_path / "manifest.json", tmp_path / "state.json")
    released = recovered.release_or_expire_lease("TASK-A", "worker-2")
    assert released["execution_status"] == "READY"

    bad = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    bad["tasks"]["TASK-BLOCKED"] = {"execution_status": "COMPLETED"}
    (tmp_path / "state.json").write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="contradicts"):
        TaskCoordinator(tmp_path / "manifest.json", tmp_path / "state.json")
