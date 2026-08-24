#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from review import ManualReviewStore, review_metrics
from review.manual import effective_items, effective_review_queue
from automation.orchestrator import AgentOrchestrator


def _load(path: Path):
    value = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
    if not isinstance(value, list):
        raise ValueError(f"Expected JSON list: {path}")
    return value


def _store(args):
    return ManualReviewStore(args.queue, args.decisions)


def _filtered(args, store):
    values = effective_items(store.items(), store.decisions())
    if getattr(args, "finding_type", None):
        values = [item for item in values if item["finding_type"] == args.finding_type]
    if getattr(args, "province", None):
        values = [item for item in values if item["province"] == args.province]
    if getattr(args, "organization", None):
        values = [item for item in values if item["organization_id"] == args.organization]
    if getattr(args, "status", None):
        values = [item for item in values if item["disposition"] == args.status]
    return values


def main(argv=None):
    parser = argparse.ArgumentParser(description="Inspect and record auditable manual ambiguity decisions.")
    root = Path("data/generated/manual_review")
    parser.add_argument("--queue", type=Path, default=root / "queue.json")
    parser.add_argument("--decisions", type=Path, default=root / "decisions.json")
    sub = parser.add_subparsers(dest="command", required=True)
    refresh = sub.add_parser("refresh", help="Regenerate deterministic review items from current findings")
    refresh.add_argument("--review", type=Path, required=True)
    refresh.add_argument("--research", type=Path, required=True)
    refresh.add_argument("--records", type=Path, required=True)
    listing = sub.add_parser("list")
    for target in (listing,):
        target.add_argument("--finding-type")
        target.add_argument("--province")
        target.add_argument("--organization")
        target.add_argument("--status", choices=[
            "UNRESOLVED", "RESOLVED", "DEFERRED", "CONFIRMED_DUPLICATE",
            "CONFIRMED_RELATIONSHIP_PENDING_RECRAWL",
            "CONFIRMED_RELATIONSHIP_PENDING_MAPPING",
        ])
    show = sub.add_parser("show"); show.add_argument("review_id")
    decide = sub.add_parser("decide"); decide.add_argument("review_id"); decide.add_argument("decision_type")
    decide.add_argument("--actor", required=True); decide.add_argument("--note", default="")
    decide.add_argument("--evidence", action="append", default=[])
    history = sub.add_parser("history"); history.add_argument("review_id")
    sub.add_parser("stats")
    apply = sub.add_parser("apply", help="Write a non-destructive effective finding/readiness view")
    apply.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    store = _store(args)
    if args.command == "refresh":
        items = store.refresh(_load(args.review), _load(args.research), _load(args.records))
        output = {"review_items": len(items), "queue": str(args.queue)}
    elif args.command == "list":
        output = _filtered(args, store)
    elif args.command == "show":
        output = next((item for item in effective_items(store.items(), store.decisions()) if item["review_id"] == args.review_id), None)
        if output is None: parser.error("unknown review item")
    elif args.command == "decide":
        decision, created = store.decide(args.review_id, args.decision_type, args.actor,
            note=args.note, evidence_references=args.evidence)
        output = {"created": created, "decision": decision}
    elif args.command == "history":
        output = [item for item in store.decisions() if item.get("review_id") == args.review_id]
    elif args.command == "apply":
        output = effective_review_queue(store.items(), store.decisions())
        AgentOrchestrator._atomic_json(args.output, output)
        output = {"organizations": len(output), "output": str(args.output)}
    else:
        output = review_metrics(store.items(), store.decisions())
    print(json.dumps(output, indent=2, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
