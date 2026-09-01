"""Bounded cross-task coordination for the audited recovery queue.

This module plans work only. It does not spawn processes, call networks, write
databases, deploy services, or send outreach. A supervising operator/agent is
responsible for assigning a ready task to the appropriate bounded command or
external collaboration agent and then recording its outcome.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


TERMINAL = {"COMPLETED", "SKIPPED"}
VALID = TERMINAL | {"PENDING", "RUNNING", "BLOCKED", "FAILED"}


class TaskCoordinator:
    schema_version = 1

    def __init__(self, manifest_path: Path, state_path: Path):
        self.manifest_path = Path(manifest_path)
        self.state_path = Path(state_path)
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema_version") != self.schema_version:
            raise ValueError("Unsupported task manifest schema")
        self.tasks = {item["id"]: dict(item) for item in manifest.get("tasks", [])}
        if len(self.tasks) != len(manifest.get("tasks", [])):
            raise ValueError("Task IDs must be unique")
        for task in self.tasks.values():
            unknown = set(task.get("depends_on", [])) - self.tasks.keys()
            if unknown:
                raise ValueError(f"Unknown dependencies for {task['id']}: {sorted(unknown)}")
        self.state = self._load_state()

    def _load_state(self):
        if not self.state_path.is_file():
            return {"schema_version": self.schema_version, "tasks": {}}
        value = json.loads(self.state_path.read_text(encoding="utf-8"))
        if value.get("schema_version") != self.schema_version or not isinstance(value.get("tasks"), dict):
            raise ValueError("Unsupported or malformed coordinator state")
        for task_id, item in value["tasks"].items():
            if task_id not in self.tasks or item.get("status") not in VALID:
                raise ValueError("Coordinator state contains an unknown task or status")
        return value

    def status(self, task_id: str) -> str:
        return self.state["tasks"].get(task_id, {}).get("status", "PENDING")

    def ready(self):
        return [task for task in self.tasks.values()
                if self.status(task["id"]) == "PENDING"
                and all(self.status(dep) in TERMINAL for dep in task.get("depends_on", []))]

    def blocked(self):
        return [task for task in self.tasks.values()
                if self.status(task["id"]) == "PENDING"
                and any(self.status(dep) not in TERMINAL for dep in task.get("depends_on", []))]

    def snapshot(self) -> dict[str, Any]:
        return {
            "tasks": [{**task, "status": self.status(task["id"]),
                       "dependency_status": {dep: self.status(dep) for dep in task.get("depends_on", [])}}
                      for task in self.tasks.values()],
            "ready": [task["id"] for task in self.ready()],
            "blocked": [task["id"] for task in self.blocked()],
        }


def main():
    parser = argparse.ArgumentParser(description="Plan audited repository tasks without executing them.")
    parser.add_argument("--manifest", default="automation/task_manifest.json")
    parser.add_argument("--state", default="data/generated/task_coordinator/state.json")
    args = parser.parse_args()
    print(json.dumps(TaskCoordinator(Path(args.manifest), Path(args.state)).snapshot(), indent=2))


if __name__ == "__main__":
    main()
