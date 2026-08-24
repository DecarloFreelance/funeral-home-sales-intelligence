#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from bs4 import BeautifulSoup

from automation.orchestrator import AgentOrchestrator
from enrichment.forms import analyze_dataset


def _load(path: Path, expected):
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, expected): raise ValueError(f"Malformed input: {path}")
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description="Extract neutral, non-submitting public form intelligence.")
    parser.add_argument("--data", type=Path, default=Path("data/generated/forms/form_intelligence.json"))
    sub = parser.add_subparsers(dest="command", required=True)
    analyze = sub.add_parser("analyze")
    analyze.add_argument("--records", type=Path, default=Path("data/generated/scale/enriched_results.json"))
    analyze.add_argument("--pages", type=Path, default=Path("data/generated/scale/pages.json"))
    analyze.add_argument("--additional-html", nargs=3, metavar=("ORGANIZATION", "URL", "PATH"), action="append", default=[])
    analyze.add_argument("--observed-at", default="UNKNOWN")
    listing = sub.add_parser("list"); listing.add_argument("--organization"); listing.add_argument("--semantic-category"); listing.add_argument("--form-type"); listing.add_argument("--action-scope")
    show = sub.add_parser("show"); show.add_argument("identifier")
    sub.add_parser("stats")
    candidates = sub.add_parser("review-candidates"); candidates.add_argument("--reason")
    args = parser.parse_args(argv)
    if args.command == "analyze":
        pages = _load(args.pages, list)
        for organization, url, path in args.additional_html:
            html = Path(path).read_text(encoding="utf-8")
            text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
            pages.append({"url": url, "html": html, "text": text, "metadata": {},
                          "crawl": {"observedAt": args.observed_at},
                          "discovery": {"queue_domain": organization, "source": "operator_authorized_first_party_capture"}})
        package = analyze_dataset(_load(args.records, list), pages, args.observed_at)
        existing = _load(args.data, dict) if args.data.is_file() else None
        changed = package != existing
        if changed: AgentOrchestrator._atomic_json(args.data, package)
        output = {"created_or_updated": changed, "organizations": package["organization_count"],
                  "organizations_with_forms": package["organizations_with_forms"], "forms": package["total_forms"],
                  "review_candidates": len(package["review_candidates"]), "form_submissions": 0}
    else:
        package = _load(args.data, dict)
        if args.command == "stats": output = {"organizations": package["organization_count"], "organizations_with_forms": package["organizations_with_forms"], "total_forms": package["total_forms"], **package["metrics"]}
        elif args.command == "review-candidates": output = [item for item in package["review_candidates"] if not args.reason or args.reason in item["candidate_reasons"]]
        elif args.command == "show": output = [item for item in package["forms"] if args.identifier in {item["organization_id"], item["form_id"]}]
        else:
            output = package["forms"]
            if args.organization: output = [item for item in output if item["organization_id"] == args.organization]
            if args.semantic_category: output = [item for item in output if args.semantic_category in item["semantic_category_counts"]]
            if args.form_type: output = [item for item in output if item["form_type"] == args.form_type]
            if args.action_scope: output = [item for item in output if item["action_scope"] == args.action_scope]
    print(json.dumps(output, indent=2, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__": main()
