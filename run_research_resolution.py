#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from automation import AgentOrchestrator
from automation.runner_bridge import coordinated_run
from automation.task_coordinator import TaskCoordinator
from research import ResearchResolutionAgent, build_resolution_queue
from persistence.file_lock import exclusive


def _load(path: Path, expected):
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, expected):
        raise ValueError(f"Malformed research input: {path}")
    return value


def run(research_path: Path, review_path: Path, output_path: Path, queue_path: Path,
        state_path: Path, audit_path: Path):
    research = _load(research_path, list)
    review = _load(review_path, list)
    review_by_domain = {value.get("domain"): value.get("findings", []) for value in review}
    prior = _load(output_path, list) if output_path.is_file() else []
    prior_by_domain = {value.get("domain"): value for value in prior}
    current_by_domain = {value.get("domain"): value for value in research}
    # Resolved records leave the live review queue. Retain and re-evaluate their
    # evidence so resolver-version changes can invalidate an earlier conclusion.
    # Current unresolved evidence wins when the entity remains in the queue.
    combined = {**prior_by_domain, **current_by_domain}
    for item in review:
        domain = item.get("domain")
        if domain and domain not in combined:
            combined[domain] = {"domain": domain, "status": "QUALITY_REVIEW_ONLY"}
    research = list(combined.values())
    orchestrator = AgentOrchestrator(
        state_path, audit_path, [ResearchResolutionAgent()], defer_skipped_audit=True,
    )
    records = []
    for item in research:
        domain = str(item.get("domain") or "").lower().removeprefix("www.")
        historical = [
            {
                "id": question.get("finding_id"),
                "code": question.get("finding_code"),
                "evidence": question.get("current_evidence"),
            }
            for question in (prior_by_domain.get(domain, {}).get("research_resolution") or {}).get("questions", [])
        ]
        findings = []
        seen_codes = set()
        for finding in [*(review_by_domain.get(domain) or []), *historical]:
            code = finding.get("code")
            if code in seen_codes:
                continue
            seen_codes.add(code)
            findings.append(finding)
        record = orchestrator.process({
            "domain": domain,
            "research_item": item,
            "findings": findings,
            "record": {"domain": domain, **item},
        })
        records.append(record)
    orchestrator.flush_audit()
    queue = build_resolution_queue(records)
    AgentOrchestrator._atomic_json(output_path, records)
    AgentOrchestrator._atomic_json(queue_path, queue)
    return {
        "candidates": len(records),
        "questions": sum((value.get("research_resolution") or {}).get("question_count", 0) for value in records),
        "resolved": sum(
            bool(question.get("outcome", {}).get("resolved", False))
            for value in records
            for question in (value.get("research_resolution") or {}).get("questions", [])
        ),
        "ambiguous": sum(
            not question.get("outcome", {}).get("resolved", False)
            for value in records
            for question in (value.get("research_resolution") or {}).get("questions", [])
        ),
    }


def run_locked(*args):
    state_path = Path(args[-2])
    state_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = state_path.with_suffix(state_path.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        with exclusive(lock):
            return run(*args)


def run_coordinated(research_path: Path, review_path: Path, output_path: Path, queue_path: Path,
                    state_path: Path, audit_path: Path, manifest_path: Path,
                    coordinator_state_path: Path, worker_id: str):
    coordinator = TaskCoordinator(manifest_path, coordinator_state_path)
    return coordinated_run(
        coordinator, "AUTOMATION-RESEARCH-RESOLUTION", worker_id,
        (research_path, review_path), (output_path, queue_path, state_path, audit_path),
        lambda: run_locked(research_path, review_path, output_path, queue_path, state_path, audit_path),
    )


def main():
    parser = argparse.ArgumentParser(description="Resolve explicit ambiguity questions from bounded public evidence.")
    root = Path("data/generated/enrichment")
    parser.add_argument("--research", type=Path, default=Path("data/research_queue.json"))
    parser.add_argument("--review", type=Path, default=root / "review_queue.json")
    parser.add_argument("--output", type=Path, default=root / "research_resolution_results.json")
    parser.add_argument("--queue", type=Path, default=root / "research_resolution_queue.json")
    parser.add_argument("--state", type=Path, default=root / "research_agent_state.json")
    parser.add_argument("--audit", type=Path, default=root / "research_agent_audit.json")
    parser.add_argument("--coordinator-manifest", type=Path)
    parser.add_argument("--coordinator-state", type=Path)
    parser.add_argument("--worker-id")
    args = parser.parse_args()
    if args.worker_id:
        if not args.coordinator_manifest or not args.coordinator_state:
            parser.error("--worker-id requires --coordinator-manifest and --coordinator-state")
        summary = run_coordinated(
            args.research, args.review, args.output, args.queue, args.state, args.audit,
            args.coordinator_manifest, args.coordinator_state, args.worker_id,
        )
    else:
        summary = run_locked(args.research, args.review, args.output, args.queue, args.state, args.audit)
    print("Research candidates={candidates} questions={questions} resolved={resolved} ambiguous={ambiguous}".format(**summary))


if __name__ == "__main__":
    main()
