#!/usr/bin/env python3
"""Bounded national discovery planning, execution, and status reporting."""
import argparse
import fcntl
import json
from pathlib import Path
import sys

from discovery.autonomous import (
    DiscoveryBudget, DiscoveryStore, NationalDiscoveryCoordinator, QueryPlanner,
    coverage_report, saturation_status,
)


DEFAULT_ROOT = Path("data/generated/autonomous_discovery")


def load_json(path, default):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


class JsonSearchProvider:
    """Deterministic adapter for an authorized provider export/fixture.

    The input is keyed by exact query, or is a list returned for every query.
    This does not represent search results as first-party evidence: each row must
    include a separate ``verification`` object for fixture validation.
    """
    name = "json_export"
    def __init__(self, path): self.payload = load_json(path, {})
    def search(self, query, *, cursor="", limit=20):
        rows = self.payload.get(query, []) if isinstance(self.payload, dict) else self.payload
        return {"results": list(rows)[:limit], "status": "OK", "cost": 1}


def fixture_verifier(candidate):
    raw = candidate.get("raw_source_value") or {}
    return dict(raw.get("verification") or {"reachable": False, "retryable": False})


def budget_from_args(args):
    return DiscoveryBudget(
        max_queries=args.budget, max_candidates=args.max_candidates,
        max_verification_fetches=args.max_verification_fetches,
        max_pages_per_candidate=args.max_pages, concurrency=args.concurrency,
        per_host_delay=args.per_host_delay, retry_limit=args.retries,
        timeout=args.timeout, max_runtime_seconds=args.max_runtime,
    )


def render_status(store, seed):
    organizations = list(store.data["organizations"].values()) or seed
    return {
        "current_coverage": coverage_report(organizations, store.data["candidates"].values()),
        "this_run": store.data["runs"][-1] if store.data["runs"] else {},
        "novelty": saturation_status(store.data["query_ledger"], DiscoveryBudget()),
        "query_ledger": {"entries": len(store.data["query_ledger"]), "completed": sum(x.get("status") == "COMPLETED" for x in store.data["query_ledger"].values())},
        "quarantine_reasons": _reason_counts(store.data["review_queue"].values()),
    }


def _reason_counts(rows):
    counts = {}
    for row in rows:
        for reason in row.get("reasons", []): counts[reason] = counts.get(reason, 0) + 1
    return counts


def parser():
    root = argparse.ArgumentParser(description="Evidence-preserving Canadian funeral-service discovery")
    sub = root.add_subparsers(dest="command", required=True)
    run = sub.add_parser("autonomous")
    run.add_argument("--country", default="CA", choices=["CA"])
    run.add_argument("--budget", type=int, default=100)
    run.add_argument("--max-candidates", type=int, default=500)
    run.add_argument("--max-verification-fetches", type=int, default=100)
    run.add_argument("--max-pages", type=int, default=4)
    run.add_argument("--concurrency", type=int, default=1)
    run.add_argument("--per-host-delay", type=float, default=.25)
    run.add_argument("--retries", type=int, default=2)
    run.add_argument("--timeout", type=float, default=15)
    run.add_argument("--max-runtime", type=int, default=1800)
    run.add_argument("--plan-only", action="store_true")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--search-export", type=Path, help="Authorized provider JSON export; no general search provider is bundled")
    run.add_argument("--seed", type=Path, default=Path("data/generated/scale/crawl_queue.json"))
    run.add_argument("--state", type=Path, default=DEFAULT_ROOT / "state.json")
    run.add_argument("--report", type=Path, default=DEFAULT_ROOT / "report.json")
    status = sub.add_parser("autonomous-status")
    status.add_argument("--seed", type=Path, default=Path("data/generated/scale/crawl_queue.json"))
    status.add_argument("--state", type=Path, default=DEFAULT_ROOT / "state.json")
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    seed = load_json(args.seed, [])
    store = DiscoveryStore(args.state)
    if args.command == "autonomous-status":
        print(json.dumps(render_status(store, seed), indent=2)); return 0
    budget = budget_from_args(args)
    provider_name = "json_export" if args.search_export else "UNCONFIGURED_SEARCH_PROVIDER"
    plan = QueryPlanner(provider_name).plan(seed, store.data["query_ledger"], limit=budget.max_queries)
    if args.plan_only:
        print(json.dumps({"provider": provider_name, "mutated": False, "queries": [x.__dict__ for x in plan]}, indent=2, ensure_ascii=False)); return 0
    if not args.search_export:
        print("No authorized search provider is configured. Use --plan-only or supply --search-export.", file=sys.stderr); return 3
    lock_path = args.state.with_suffix(args.state.suffix + ".lock"); lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock:
        try: fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another autonomous discovery run holds the process lock.", file=sys.stderr); return 4
        if not args.dry_run:
            store.seed(seed); store.save()
        summary = NationalDiscoveryCoordinator(store, JsonSearchProvider(args.search_export), fixture_verifier, budget).run(plan, dry_run=args.dry_run)
        report = {"current_coverage": coverage_report((store.data["organizations"].values() if not args.dry_run else seed), store.data["candidates"].values()), "this_run": summary, "novelty": saturation_status(store.data["query_ledger"], budget), "quarantine_reasons": _reason_counts(store.data["review_queue"].values())}
        if not args.dry_run:
            from automation.orchestrator import AgentOrchestrator
            AgentOrchestrator._atomic_json(args.report, report)
        print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__": raise SystemExit(main())
