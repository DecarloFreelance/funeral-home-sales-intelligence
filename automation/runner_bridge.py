"""Connect approved bounded runners to the task control plane.

This bridge coordinates ownership and evidence of execution only. It never
invokes CRM, outreach, network, database, browser, or deployment actions.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable, Iterable

from automation.task_coordinator import TaskCoordinator


def fingerprint_paths(paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        value = Path(path)
        digest.update(str(value.name).encode("utf-8"))
        digest.update(b"\0")
        digest.update(value.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def coordinated_run(
    coordinator: TaskCoordinator,
    task_id: str,
    worker_id: str,
    input_paths: Iterable[Path],
    output_paths: Iterable[Path],
    run: Callable[[], dict],
) -> dict:
    """Claim, execute one bounded runner, and reconcile its result."""
    inputs = tuple(Path(path) for path in input_paths)
    outputs = tuple(Path(path) for path in output_paths)
    input_fingerprint = fingerprint_paths(inputs)
    claim = coordinator.claim_task(task_id, worker_id, coordinator.task_version(task_id), input_fingerprint)
    if claim.get("reused"):
        return (claim.get("completion") or {}).get("summary", {})
    coordinator.renew_lease(task_id, worker_id, 1)
    try:
        summary = run()
        completion_fingerprint = fingerprint_paths(outputs)
        review_status = "REVIEW" if (
            summary.get("needs_review", 0) or summary.get("ambiguous", 0) or summary.get("review_required", 0)
        ) else "REVIEW"
        coordinator.reconcile_completion(task_id, worker_id, {
            "task_version": coordinator.task_version(task_id),
            "input_fingerprint": input_fingerprint,
            "completion_fingerprint": completion_fingerprint,
            "outcome": "COMPLETED",
            "review_status": review_status,
            "summary": summary,
        })
        return summary
    except Exception as error:
        failure_fingerprint = hashlib.sha256(
            json.dumps({"type": type(error).__name__, "message": str(error)[:500]}, sort_keys=True).encode("utf-8")
        ).hexdigest()
        coordinator.reconcile_completion(task_id, worker_id, {
            "task_version": coordinator.task_version(task_id),
            "input_fingerprint": input_fingerprint,
            "completion_fingerprint": failure_fingerprint,
            "outcome": "FAILED",
            "review_status": "REVIEW",
            "error_class": type(error).__name__,
        })
        raise
