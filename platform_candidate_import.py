#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

from discovery.ingestion import DiscoveryLead, build_crawl_queue


def build_candidate_queue(records):
    valid = []
    metadata = {}
    for record in records:
        lead = DiscoveryLead.from_mapping({
            **record,
            "category": "platform_candidate",
            "source": "platform_research",
            "source_url": record.get("evidence_url", ""),
        })
        if not lead.domain:
            continue
        valid.append(lead)
        metadata[lead.domain] = record

    queue = build_crawl_queue(valid)
    for item in queue:
        candidate = metadata[item["domain"]]
        item.update({
            "record_type": "platform_candidate",
            "candidate_type": candidate.get("candidate_type", ""),
            "offers": candidate.get("offers", []),
            "downstream_markets": candidate.get("downstream_markets", []),
            "recommended_motion": candidate.get("recommended_motion", ""),
            "evidence": candidate.get("evidence", ""),
            "evidence_url": candidate.get("evidence_url", ""),
        })
    return queue


def main():
    parser = argparse.ArgumentParser(description="Build the separate platform-candidate crawl queue.")
    parser.add_argument("--input", type=Path, default=Path("data/seeds/platform_candidates.json"))
    parser.add_argument("--output", type=Path, default=Path("data/generated/platform/platform_candidate_queue.json"))
    args = parser.parse_args()
    records = json.loads(args.input.read_text(encoding="utf-8"))
    queue = build_candidate_queue(records)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(queue, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Prepared {len(queue)} platform candidates in {args.output}")


if __name__ == "__main__":
    main()
