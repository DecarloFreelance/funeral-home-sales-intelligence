#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

from automation.metrics import build_metrics
from automation.orchestrator import AgentOrchestrator


def _load(path, default):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def generate(results_path, review_path, state_path, audit_path, output_path, history_path):
    history = _load(history_path, [])
    baseline = history[-1] if isinstance(history, list) and history else None
    metrics = build_metrics(
        _load(results_path, []), _load(review_path, []),
        _load(state_path, {"tasks": {}}), _load(audit_path, []), baseline=baseline,
    )
    if not isinstance(history, list):
        raise ValueError("Metrics history must be a JSON list")
    if not history or history[-1].get("snapshot_id") != metrics["snapshot_id"]:
        history.append(metrics)
    AgentOrchestrator._atomic_json(Path(output_path), metrics)
    AgentOrchestrator._atomic_json(Path(history_path), history)
    return metrics, len(history)


def main():
    parser = argparse.ArgumentParser(description="Generate reproducible enrichment gap metrics.")
    root = "data/generated/enrichment"
    parser.add_argument("--results", default=f"{root}/results.json")
    parser.add_argument("--review", default=f"{root}/review_queue.json")
    parser.add_argument("--state", default=f"{root}/agent_state.json")
    parser.add_argument("--audit", default=f"{root}/agent_audit.json")
    parser.add_argument("--output", default=f"{root}/gap_metrics.json")
    parser.add_argument("--history", default=f"{root}/gap_metrics_history.json")
    args = parser.parse_args()
    metrics, snapshots = generate(*(Path(value) for value in (
        args.results, args.review, args.state, args.audit, args.output, args.history,
    )))
    print(
        f"Organizations={metrics['organizations']} facts={metrics['facts']} "
        f"review={metrics['review_required']} stale={metrics['stale_facts']} "
        f"regressions={len(metrics['regressions'])} snapshots={snapshots}"
    )


if __name__ == "__main__":
    main()
