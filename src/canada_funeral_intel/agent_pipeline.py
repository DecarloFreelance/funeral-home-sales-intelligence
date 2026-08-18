from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from canada_funeral_intel.business_intelligence.cli import (
    run_business_facts_agent,
    run_business_facts_agent_apply,
)
from canada_funeral_intel.people.cli import run_people_review_agent, run_people_review_populate
from canada_funeral_intel.verification.website_cli import (
    run_website_candidate_review_agent,
    run_website_candidate_review_apply,
    run_website_discovery_agent,
    run_website_discovery_apply,
    run_website_process_approved,
)


class AgentPipelineError(RuntimeError):
    """Raised when the staged enrichment runner cannot continue safely."""


def _emit(progress: Callable[[str], None], stage: str, payload: object) -> None:
    progress(f"\n[{stage}]")
    progress(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))


def _approved_website_ids(
    connection: sqlite3.Connection, review_artifact: Path, minimum_confidence: float
) -> list[int]:
    artifact = json.loads(review_artifact.read_text(encoding="utf-8"))
    queue_ids = {
        int(item["queue_id"])
        for item in artifact.get("recommendations", [])
        if item.get("decision") == "approved"
        and float(item.get("confidence", 0)) >= minimum_confidence
    }
    if not queue_ids:
        return []
    marks = ",".join("?" for _ in queue_ids)
    rows = connection.execute(
        f"SELECT website_id FROM website_review_queue WHERE id IN ({marks}) AND status='approved'",
        tuple(queue_ids),
    ).fetchall()
    return list(dict.fromkeys(int(row["website_id"]) for row in rows))


def run_agent_pipeline(
    connection: sqlite3.Connection,
    *,
    model: str,
    provider: str,
    output_dir: Path,
    entity_limit: int = 10,
    queue_limit: int = 10,
    live_search: bool = True,
    search_provider: str = "searxng",
    apply: bool = False,
    process_approved: bool = False,
    review_facts: bool = False,
    review_people: bool = True,
    minimum_confidence: float = 0.85,
    progress: Callable[[str], None] = print,
) -> dict[str, object]:
    if process_approved and not apply:
        raise AgentPipelineError("--process-approved requires --apply")
    if not 1 <= entity_limit <= 25 or not 1 <= queue_limit <= 25:
        raise AgentPipelineError("entity_limit and queue_limit must be between 1 and 25")
    if not 0 <= minimum_confidence <= 1:
        raise AgentPipelineError("minimum_confidence must be between 0 and 1")
    output_dir.mkdir(parents=True, exist_ok=True)
    run_dir = output_dir / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    run_dir.mkdir()
    results: dict[str, object] = {
        "apply": apply,
        "dry_run": not apply,
        "output_dir": str(run_dir),
        "stages": [],
    }

    discovery_path = run_dir / "website-discovery.json"
    progress("[agent-pipeline] starting; database changes are disabled" if not apply else "[agent-pipeline] starting with apply enabled")
    discovery = run_website_discovery_agent(
        connection, model=model, provider=provider, output=discovery_path,
        entity_limit=entity_limit, live_search=live_search,
        search_provider=search_provider,
    )
    _emit(progress, "website discovery", discovery)
    results["stages"].append({"name": "website_discovery", "result": discovery})

    discovery_apply = run_website_discovery_apply(
        connection, input_path=discovery_path, apply=apply
    )
    _emit(progress, "website candidate queue", discovery_apply)
    results["stages"].append({"name": "website_candidate_queue", "result": discovery_apply})

    review_path = run_dir / "website-review.json"
    review = run_website_candidate_review_agent(
        connection, model=model, provider=provider, output=review_path,
        queue_limit=queue_limit,
    )
    _emit(progress, "website candidate review", review)
    results["stages"].append({"name": "website_candidate_review", "result": review})

    effective_path = run_dir / "website-review-effective.json"
    review_artifact = json.loads(review_path.read_text(encoding="utf-8"))
    overrides = 0
    for item in review_artifact.get("recommendations", []):
        if item.get("decision") == "approved" and float(item.get("confidence", 0)) < minimum_confidence:
            item["decision"] = "deferred"
            item["reviewer_note"] = (
                f"Auto-deferred below pipeline confidence threshold {minimum_confidence:.2f}. "
                + str(item.get("reviewer_note") or item.get("rationale") or "")
            ).strip()
            overrides += 1
    effective_path.write_text(json.dumps(review_artifact, indent=2, ensure_ascii=False) + "\n")
    review_apply = run_website_candidate_review_apply(
        connection, input_path=effective_path, apply=apply
    )
    review_apply["confidence_overrides"] = overrides
    _emit(progress, "website review decisions", review_apply)
    results["stages"].append({"name": "website_review_decisions", "result": review_apply})

    if process_approved and apply:
        website_ids = _approved_website_ids(connection, effective_path, minimum_confidence)
        processed: list[object] = []
        for website_id in website_ids:
            item = run_website_process_approved(
                connection, limit=1, target_website_id=website_id,
                user_agent="CanadaFuneralIntel/0.1", timeout_seconds=10,
                max_redirects=5, max_pages=25, max_depth=2,
                engine="http", fallback_playwright=True,
            )
            processed.append(item)
            progress(f"[approved website {website_id}] completed")
        results["stages"].append({"name": "approved_website_processing", "website_ids": website_ids, "result": processed})

    if review_people:
        people_queue = run_people_review_populate(connection)
        _emit(progress, "people queue", people_queue)
        people_path = run_dir / "people-review.json"
        people = run_people_review_agent(
            connection, model=model, provider=provider, output=people_path,
            agent="people-review",
        )
        _emit(progress, "people review (artifact only)", people)
        results["stages"].append({"name": "people_review", "result": people})

    if review_facts:
        facts_path = run_dir / "business-facts-review.json"
        facts = run_business_facts_agent(
            connection, model=model, provider=provider, output=facts_path,
        )
        _emit(progress, "business facts review", facts)
        facts_apply = run_business_facts_agent_apply(
            connection, input_path=facts_path, apply=apply
        )
        _emit(progress, "business facts decisions", facts_apply)
        results["stages"].append({"name": "business_facts_review", "result": facts_apply})

    progress("[agent-pipeline] complete; inspect artifacts before the next run")
    return results
