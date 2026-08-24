#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pilot import PilotStore, build_pilot_cohort


def _json(path: Path, expected):
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, expected):
        raise ValueError(f"Malformed input: {path}")
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description="Operate the manually controlled first-revenue pilot.")
    root = Path("data/generated/pilot")
    parser.add_argument("--cohort", type=Path, default=root / "cohort.json")
    parser.add_argument("--events", type=Path, default=Path("data/private/pilot_events.json"))
    sub = parser.add_subparsers(dest="command", required=True)
    generate = sub.add_parser("generate")
    generate.add_argument("--results", type=Path, default=Path("data/generated/scale/enriched_results.json"))
    generate.add_argument("--commercial", type=Path, default=Path("data/generated/scale/commercial_readiness.json"))
    generate.add_argument("--limit", type=int, default=10)
    listing = sub.add_parser("list"); listing.add_argument("--state")
    for name in ("show", "audit", "history"):
        target = sub.add_parser(name); target.add_argument("identifier")
    review = sub.add_parser("review"); review.add_argument("identifier"); review.add_argument("--actor", required=True); review.add_argument("--note", default="")
    approve = sub.add_parser("approve"); approve.add_argument("identifier"); approve.add_argument("--actor", required=True); approve.add_argument("--note", default=""); approve.add_argument("--results", type=Path, default=Path("data/generated/scale/enriched_results.json"))
    defer = sub.add_parser("defer"); defer.add_argument("identifier"); defer.add_argument("--actor", required=True); defer.add_argument("--note", default="")
    disqualify = sub.add_parser("disqualify"); disqualify.add_argument("identifier"); disqualify.add_argument("--actor", required=True); disqualify.add_argument("--note", required=True)
    draft = sub.add_parser("draft"); draft.add_argument("identifier"); draft.add_argument("--actor", required=True)
    transition = sub.add_parser("transition"); transition.add_argument("identifier"); transition.add_argument("state"); transition.add_argument("--actor", required=True); transition.add_argument("--note", default=""); transition.add_argument("--reply-sentiment"); transition.add_argument("--activity-reference", action="append", default=[])
    offer = sub.add_parser("offer"); offer.add_argument("identifier"); offer.add_argument("variant"); offer.add_argument("--actor", required=True); offer.add_argument("--quoted", type=float, default=0); offer.add_argument("--accepted", type=float, default=0); offer.add_argument("--recurring", type=float, default=0); offer.add_argument("--note", default="")
    sub.add_parser("stats")
    args = parser.parse_args(argv)
    store = PilotStore(args.cohort, args.events)
    if args.command == "generate":
        cohort = build_pilot_cohort(_json(args.results, list), _json(args.commercial, dict), limit=args.limit)
        changed = store.save_cohort(cohort)
        output = {"created_or_updated": changed, "cohort_id": cohort["cohort_id"], "prospects": len(cohort["prospects"]), "outreach_sent": False}
    elif args.command == "list":
        output = store.effective()
        if args.state:
            output = [item for item in output if item["current_state"] == args.state.upper()]
    elif args.command == "show":
        output = next((item for item in store.effective() if args.identifier in {item["pilot_id"], item["organization_id"]}), None)
        if output is None: parser.error("unknown pilot prospect")
    elif args.command == "audit":
        output = store._prospect(args.identifier)["audit_package"]
    elif args.command == "history":
        output = store.history(args.identifier)
    elif args.command == "review":
        event, created = store.transition(args.identifier, "MANUAL_REVIEW", args.actor, note=args.note); output = {"created": created, "event": event}
    elif args.command == "approve":
        event, created = store.approve(args.identifier, args.actor, _json(args.results, list), note=args.note); output = {"created": created, "event": event}
    elif args.command == "defer":
        event, created = store.transition(args.identifier, "DEFERRED", args.actor, note=args.note); output = {"created": created, "event": event}
    elif args.command == "disqualify":
        event, created = store.transition(args.identifier, "DISQUALIFIED", args.actor, note=args.note); output = {"created": created, "event": event}
    elif args.command == "draft":
        event, created = store.prepare_draft(args.identifier, args.actor); output = {"created": created, "draft": event.get("draft"), "outreach_sent": False}
    elif args.command == "transition":
        event, created = store.transition(args.identifier, args.state, args.actor, note=args.note, reply_sentiment=args.reply_sentiment, activity_references=args.activity_reference); output = {"created": created, "event": event}
    elif args.command == "offer":
        event, created = store.assign_offer(args.identifier, args.variant, args.actor, quoted_amount=args.quoted, accepted_amount=args.accepted, recurring_amount=args.recurring, note=args.note); output = {"created": created, "event": event}
    else:
        output = store.stats()
    print(json.dumps(output, indent=2, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
