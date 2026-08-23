from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid
from typing import Any, Dict, Iterable

from automation.agents import RecordAgent


TERMINAL = {"COMPLETED", "SKIPPED", "BLOCKED", "FAILED", "NEEDS_REVIEW"}


class AgentPipelineError(RuntimeError):
    """Base error for a record that must not be published."""


class AgentBlockedError(AgentPipelineError):
    pass


class AgentExecutionError(AgentPipelineError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _fingerprint(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class AgentOrchestrator:
    """Sequential per-record runner with durable state and bounded retries."""

    schema_version = 1

    def __init__(self, state_path: Path, audit_path: Path, agents: Iterable[RecordAgent]):
        self.state_path = Path(state_path)
        self.audit_path = Path(audit_path)
        self.agents = list(agents)
        self.state = self._load_state()
        self.run_id = uuid.uuid4().hex

    def _load_state(self):
        if not self.state_path.is_file():
            return {"schema_version": self.schema_version, "tasks": {}}
        value = json.loads(self.state_path.read_text(encoding="utf-8"))
        if value.get("schema_version") != self.schema_version or not isinstance(value.get("tasks"), dict):
            raise ValueError("Unsupported or malformed agent state")
        changed = False
        for task in value["tasks"].values():
            if task.get("status") == "RUNNING":
                task["status"] = "FAILED"
                task["retryable"] = True
                task["error_class"] = "INTERRUPTED"
                task["error"] = "Previous process ended before the agent recorded an outcome."
                task["completed_at"] = _now()
                changed = True
        if changed:
            self._atomic_json(self.state_path, value)
        return value

    @staticmethod
    def _atomic_json(path: Path, value: Any):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(path)

    def _save(self):
        self._atomic_json(self.state_path, self.state)

    def _audit(self, entity_id: str, agent: RecordAgent, outcome: str, **details):
        existing = []
        if self.audit_path.is_file():
            value = json.loads(self.audit_path.read_text(encoding="utf-8"))
            if isinstance(value, list):
                existing = value
        event = {
            "id": uuid.uuid4().hex,
            "run_id": self.run_id,
            "agent": agent.name,
            "agent_version": agent.version,
            "entity": entity_id,
            "timestamp": _now(),
            "outcome": outcome,
            **details,
        }
        existing.append(event)
        self._atomic_json(self.audit_path, existing)

    def process(self, context: Dict[str, Any]) -> Dict[str, Any]:
        entity_id = str(context.get("domain") or "").strip().lower()
        if not entity_id:
            raise ValueError("Agent context requires a domain entity identifier")
        working = {**context, "domain": entity_id, "record": dict(context.get("record") or {})}

        for agent in self.agents:
            payload = agent.fingerprint_payload(working)
            fingerprint = _fingerprint({"version": agent.version, "input": payload})
            key = f"{entity_id}:{agent.name}"
            previous = self.state["tasks"].get(key, {})
            if previous.get("status") == "COMPLETED" and previous.get("input_fingerprint") == fingerprint:
                working["record"].update(previous.get("output") or {})
                self._audit(entity_id, agent, "SKIPPED", reason="UNCHANGED_INPUT", retry_count=previous.get("attempts", 0))
                continue

            attempts = previous.get("attempts", 0) if previous.get("input_fingerprint") == fingerprint else 0
            if attempts >= agent.max_attempts:
                self._audit(entity_id, agent, "BLOCKED", reason="RETRY_LIMIT", retry_count=attempts)
                raise AgentBlockedError(
                    f"Agent {agent.name} is blocked for {entity_id}: retry limit reached"
                )

            task = {
                "agent": agent.name,
                "agent_version": agent.version,
                "entity": entity_id,
                "status": "RUNNING",
                "input_fingerprint": fingerprint,
                "attempts": attempts + 1,
                "started_at": _now(),
                "completed_at": None,
                "retryable": False,
            }
            self.state["tasks"][key] = task
            self._save()
            self._audit(entity_id, agent, "RUNNING", retry_count=attempts)
            try:
                output = agent.run(working)
                if not isinstance(output, dict):
                    raise TypeError("Agent output must be a mapping")
                working["record"].update(output)
                task.update(status="COMPLETED", completed_at=_now(), output=output)
                self._save()
                produced = sum(
                    value.get("fact_count", value.get("finding_count", 1)) if isinstance(value, dict) else 1
                    for value in output.values()
                )
                self._audit(entity_id, agent, "COMPLETED", retry_count=attempts, evidence_produced=produced)
            except Exception as error:
                task.update(
                    status="FAILED", completed_at=_now(), retryable=task["attempts"] < agent.max_attempts,
                    error_class=type(error).__name__, error=str(error)[:500],
                )
                self._save()
                self._audit(entity_id, agent, "FAILED", retry_count=attempts,
                    error_class=type(error).__name__, retryable=task["retryable"])
                raise AgentExecutionError(
                    f"Agent {agent.name} failed for {entity_id}: {type(error).__name__}"
                ) from error
        return working["record"]
