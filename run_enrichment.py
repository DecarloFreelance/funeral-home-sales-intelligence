#!/usr/bin/env python3
import argparse
import fcntl
import json
from pathlib import Path
from urllib.parse import urlsplit

from automation import AgentOrchestrator, EnrichmentAgent, QualityControlAgent
from enrichment.quality import evaluate_dataset_quality, readiness_from_findings


def _domain(page):
    discovery = page.get("discovery") or {}
    return str(discovery.get("queue_domain") or urlsplit(page.get("url", "")).hostname or "").lower().removeprefix("www.")


def _run_locked(pages_path: Path, results_path: Path, output_path: Path, state_path: Path, audit_path: Path, review_path: Path):
    pages = json.loads(Path(pages_path).read_text(encoding="utf-8"))
    results = json.loads(Path(results_path).read_text(encoding="utf-8"))
    if not isinstance(pages, list) or not isinstance(results, list):
        raise ValueError("Pages and results inputs must be JSON lists")
    pages_by_domain = {}
    for page in pages:
        pages_by_domain.setdefault(_domain(page), []).append(page)
    orchestrator = AgentOrchestrator(
        state_path, audit_path, [EnrichmentAgent(), QualityControlAgent()],
        defer_skipped_audit=True,
    )
    enriched = []
    review = []
    for record in results:
        domain = str(record.get("domain") or "").lower().removeprefix("www.")
        output = orchestrator.process({"domain": domain, "pages": pages_by_domain.get(domain, []), "record": record})
        enriched.append(output)
    orchestrator.flush_audit()
    dataset_findings = evaluate_dataset_quality(enriched)
    for output in enriched:
        domain = output.get("domain", "")
        quality = output.get("quality_control") or {}
        combined = {item["id"]: item for item in [*(quality.get("findings") or []), *dataset_findings.get(domain, [])]}
        quality["findings"] = sorted(combined.values(), key=lambda item: item["code"])
        quality["finding_count"] = len(quality["findings"])
        quality["status"] = "NEEDS_REVIEW" if any(item["requires_review"] for item in quality["findings"]) else "PASSED"
        quality.update(readiness_from_findings(quality["findings"]))
        output["quality_control"] = quality
        if quality.get("status") == "NEEDS_REVIEW":
            review.append({
                "domain": domain,
                "status": "NEEDS_REVIEW",
                "findings": quality.get("findings", []),
                "recommended_next_research": [item["recommended_action"] for item in quality.get("findings", [])],
                "crm_sync_safe": quality["crm_sync_safe"],
                "outreach_ready": quality["outreach_ready"],
            })
    AgentOrchestrator._atomic_json(output_path, enriched)
    AgentOrchestrator._atomic_json(review_path, review)
    return {"records": len(enriched), "needs_review": len(review)}


def run(pages_path: Path, results_path: Path, output_path: Path, state_path: Path, audit_path: Path, review_path: Path):
    """Serialize writers so concurrent invocations cannot corrupt task state."""
    state_path = Path(state_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = state_path.with_suffix(state_path.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            return _run_locked(pages_path, results_path, output_path, state_path, audit_path, review_path)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def main():
    parser = argparse.ArgumentParser(description="Run bounded local enrichment and quality agents.")
    parser.add_argument("--pages", default="data/discovered_leads.json")
    parser.add_argument("--results", default="data/discovered_results.json")
    parser.add_argument("--output", default="data/generated/enrichment/results.json")
    parser.add_argument("--state", default="data/generated/enrichment/agent_state.json")
    parser.add_argument("--audit", default="data/generated/enrichment/agent_audit.json")
    parser.add_argument("--review", default="data/generated/enrichment/review_queue.json")
    args = parser.parse_args()
    summary = run(*(Path(value) for value in (args.pages, args.results, args.output, args.state, args.audit, args.review)))
    print(f"Enriched {summary['records']} records; {summary['needs_review']} require review.")


if __name__ == "__main__":
    main()
