"""Bounded, review-aware task coordination.

The manifest declares work and historical review state. The state file records
only execution ownership and outcomes. This module never invokes workers or
performs network, CRM, database, Render, or outreach actions.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import uuid
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from persistence.file_lock import exclusive


SCHEMA_VERSION = 2
EXECUTION_STATUSES = {"DECLARED", "READY", "CLAIMED", "RUNNING", "COMPLETED", "FAILED", "BLOCKED", "CANCELLED"}
DECLARED_STATUSES = {"ACTIVE", "VALIDATED", "PARTIALLY_VALIDATED", "BLOCKED"}
TERMINAL = {"COMPLETED", "BLOCKED", "CANCELLED"}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


class TaskCoordinator:
    schema_version = SCHEMA_VERSION

    def __init__(self, manifest_path: Path, state_path: Path):
        self.manifest_path = Path(manifest_path)
        self.state_path = Path(state_path)
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("Unsupported task manifest schema")
        rows = manifest.get("tasks", [])
        self.tasks = {item["id"]: dict(item) for item in rows}
        if len(self.tasks) != len(rows):
            raise ValueError("Task IDs must be unique")
        for task in self.tasks.values():
            if task.get("task_version", 0) < 1 or task.get("declared_status") not in DECLARED_STATUSES:
                raise ValueError(f"Malformed declaration for {task.get('id')}")
            unknown = set(task.get("depends_on", [])) - self.tasks.keys()
            if unknown:
                raise ValueError(f"Unknown dependencies for {task['id']}: {sorted(unknown)}")
        self.state = self._load_state()
        self._validate_state()

    def _load_state(self):
        if not self.state_path.is_file():
            return {"schema_version": SCHEMA_VERSION, "tasks": {}, "historical_execution": {}}
        value = json.loads(self.state_path.read_text(encoding="utf-8"))
        if value.get("schema_version") == 1:
            return {
                "schema_version": SCHEMA_VERSION,
                "tasks": {},
                "historical_execution": value.get("tasks", {}),
            }
        if value.get("schema_version") != SCHEMA_VERSION or not isinstance(value.get("tasks"), dict):
            raise ValueError("Unsupported or malformed coordinator state")
        return value

    def _validate_state(self):
        for task_id, item in self.state["tasks"].items():
            declaration = self.tasks.get(task_id)
            if declaration is None:
                raise ValueError(f"State contains unknown task {task_id}")
            status = item.get("execution_status")
            if status not in EXECUTION_STATUSES:
                raise ValueError(f"Unknown execution status for {task_id}")
            if declaration["declared_status"] == "BLOCKED" and status == "COMPLETED":
                raise ValueError(f"Execution state contradicts blocked declaration for {task_id}")
            if item.get("task_version") != declaration["task_version"]:
                raise ValueError(f"State task version is stale for {task_id}")

    def _save(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temporary.write_text(json.dumps(self.state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(self.state_path)

    def _locked(self):
        lock_path = self.state_path.with_suffix(self.state_path.suffix + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        return lock_path.open("a+", encoding="utf-8")

    def _task(self, task_id: str) -> dict[str, Any]:
        if task_id not in self.tasks:
            raise ValueError(f"Unknown task {task_id}")
        return self.tasks[task_id]

    def _entry(self, task_id: str) -> dict[str, Any]:
        declaration = self._task(task_id)
        return self.state["tasks"].get(task_id, {
            "task_version": declaration["task_version"],
            "execution_status": "BLOCKED" if declaration["declared_status"] == "BLOCKED" else "DECLARED",
            "owner": None,
            "lease": None,
        })

    def status(self, task_id: str) -> str:
        return self._entry(task_id)["execution_status"]

    def task_version(self, task_id: str) -> int:
        return int(self._task(task_id)["task_version"])

    def _dependencies_complete(self, task: dict[str, Any]) -> bool:
        return all(self.status(dep) == "COMPLETED" for dep in task.get("depends_on", []))

    def list_ready_tasks(self) -> list[dict[str, Any]]:
        ready = []
        for task in self.tasks.values():
            if task["declared_status"] != "ACTIVE":
                continue
            status = self.status(task["id"])
            if status in {"DECLARED", "READY", "FAILED"} and self._dependencies_complete(task):
                ready.append({**task, "execution_status": "READY"})
        return ready

    def ready(self):
        return self.list_ready_tasks()

    def blocked(self):
        return [
            {**task, "execution_status": self.status(task["id"])}
            for task in self.tasks.values()
            if task["declared_status"] == "BLOCKED" or (
                self.status(task["id"]) not in TERMINAL and not self._dependencies_complete(task)
            )
        ]

    def claim_task(self, task_id: str, worker_id: str, expected_version: int, input_fingerprint: str, lease_seconds: int = 900):
        task = self._task(task_id)
        if task["task_version"] != expected_version:
            raise ValueError("Task version is stale")
        if not worker_id.strip() or not input_fingerprint:
            raise ValueError("Worker and input fingerprint are required")
        if task["declared_status"] != "ACTIVE" or not self._dependencies_complete(task):
            raise ValueError("Task is not ready")
        with self._locked() as lock, exclusive(lock):
            current = TaskCoordinator(self.manifest_path, self.state_path)
            entry = current._entry(task_id)
            if entry["execution_status"] == "COMPLETED" and entry.get("input_fingerprint") == input_fingerprint:
                return {**entry, "reused": True}
            if entry["execution_status"] not in {"DECLARED", "READY", "FAILED"}:
                raise ValueError("Task is already claimed or completed")
            now = _now()
            lease = {
                "worker_id": worker_id,
                "acquired_at": _iso(now),
                "expires_at": _iso(now + timedelta(seconds=lease_seconds)),
                "lease_version": 1,
            }
            entry.update({"task_version": expected_version, "execution_status": "CLAIMED", "owner": worker_id,
                          "input_fingerprint": input_fingerprint, "lease": lease})
            current.state["tasks"][task_id] = entry
            current._save()
            self.state = current.state
            return dict(entry)

    def renew_lease(self, task_id: str, worker_id: str, lease_version: int, lease_seconds: int = 900):
        with self._locked() as lock, exclusive(lock):
            current = TaskCoordinator(self.manifest_path, self.state_path)
            entry = current._entry(task_id)
            lease = entry.get("lease") or {}
            if lease.get("worker_id") != worker_id:
                raise ValueError("Lease worker mismatch")
            if lease.get("lease_version") != lease_version or _parse(lease["expires_at"]) <= _now():
                raise ValueError("Lease is stale or expired")
            lease["expires_at"] = _iso(_now() + timedelta(seconds=lease_seconds))
            lease["lease_version"] += 1
            entry["lease"] = lease
            entry["execution_status"] = "RUNNING"
            current.state["tasks"][task_id] = entry
            current._save()
            self.state = current.state
            return dict(entry)

    def reconcile_completion(self, task_id: str, worker_id: str, completion_record: dict[str, Any]):
        task = self._task(task_id)
        with self._locked() as lock, exclusive(lock):
            current = TaskCoordinator(self.manifest_path, self.state_path)
            entry = current._entry(task_id)
            if entry.get("execution_status") == "COMPLETED":
                if entry.get("completion") == completion_record:
                    return dict(entry)
                raise ValueError("Conflicting completion")
            if entry.get("owner") != worker_id:
                raise ValueError("Completion worker mismatch")
            lease = entry.get("lease") or {}
            if not lease or _parse(lease.get("expires_at", "2000-01-01T00:00:00Z")) <= _now():
                raise ValueError("Completion lease is expired")
            if entry.get("task_version") != completion_record.get("task_version"):
                raise ValueError("Completion task version mismatch")
            if entry.get("input_fingerprint") != completion_record.get("input_fingerprint"):
                raise ValueError("Completion input fingerprint mismatch")
            if not completion_record.get("completion_fingerprint"):
                raise ValueError("Completion fingerprint is required")
            outcome = str(completion_record.get("outcome") or "COMPLETED").upper()
            if outcome not in {"COMPLETED", "FAILED", "REVIEW", "UNRESOLVED"}:
                raise ValueError("Completion outcome must be COMPLETED, FAILED, REVIEW, or UNRESOLVED")
            entry.update({
                "execution_status": "FAILED" if outcome == "FAILED" else "COMPLETED",
                "completion": dict(completion_record),
                "review_status": completion_record.get("review_status", "UNRESOLVED"),
                "lease": None,
            })
            current.state["tasks"][task_id] = entry
            current._save()
            self.state = current.state
            return dict(entry)

    def release_or_expire_lease(self, task_id: str, worker_id: str):
        with self._locked() as lock, exclusive(lock):
            current = TaskCoordinator(self.manifest_path, self.state_path)
            entry = current._entry(task_id)
            lease = entry.get("lease") or {}
            if lease.get("worker_id") != worker_id and _parse(lease.get("expires_at", "9999-01-01T00:00:00Z")) > _now():
                raise ValueError("Lease worker mismatch")
            entry.update({"execution_status": "READY", "owner": None, "lease": None})
            current.state["tasks"][task_id] = entry
            current._save()
            self.state = current.state
            return dict(entry)

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "tasks": [{**task, "execution_status": self.status(task["id"]),
                        "dependency_status": {dep: self.status(dep) for dep in task.get("depends_on", [])}}
                       for task in self.tasks.values()],
            "ready": [task["id"] for task in self.list_ready_tasks()],
            "blocked": [task["id"] for task in self.blocked()],
        }


def main():
    parser = argparse.ArgumentParser(description="Plan bounded task execution without invoking workers.")
    parser.add_argument("--manifest", default="automation/task_manifest.json")
    parser.add_argument("--state", default="data/generated/task_coordinator/state.json")
    args = parser.parse_args()
    print(json.dumps(TaskCoordinator(Path(args.manifest), Path(args.state)).snapshot(), indent=2))


if __name__ == "__main__":
    main()
