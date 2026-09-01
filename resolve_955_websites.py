#!/usr/bin/env python3
"""Targeted website search for known directory identities.

This stage discovers candidates only. It does not claim that a search result is
an official website. Results retain search evidence for a later verification
stage.
"""

import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from discovery.langsearch_provider import LangSearchError, LangSearchProvider


EXCLUDED_HOSTS = {
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "youtube.com",
    "youtu.be",
    "x.com",
    "twitter.com",
    "yelp.ca",
    "yelp.com",
    "yellowpages.ca",
    "legacy.com",
    "tributearchive.com",
    "echovita.com",
    "everloved.com",
}


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Include the process ID so overlapping/restarted workers cannot replace
    # one another's checkpoint temporary file.
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def hostname(url):
    try:
        return (urlsplit(str(url)).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def excluded(url):
    host = hostname(url)
    return any(host == item or host.endswith("." + item) for item in EXCLUDED_HOSTS)


def targeted_query(row):
    company = str(row.get("company") or "").strip()
    city = str(row.get("city") or "").strip()
    province = str(row.get("province") or "").strip()

    parts = [
        f'"{company}"' if company else "",
        city,
        province,
        "Canada",
        "funeral home official website",
    ]

    return " ".join(part for part in parts if part)


def load_json(path, default):
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(
        description="Search LangSearch for official-site candidates for known funeral businesses."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--results-per-query", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--min-interval", type=float, default=1.05)
    args = parser.parse_args()

    rows = load_json(args.input, [])
    if not isinstance(rows, list):
        raise SystemExit("STOP: input must be a JSON list")

    args.output_dir.mkdir(parents=True, exist_ok=True)

    results_path = args.output_dir / "search_results.json"
    state_path = args.output_dir / "state.json"

    previous = load_json(results_path, [])
    if not isinstance(previous, list):
        raise SystemExit("STOP: existing search_results.json is not a list")

    by_id = {
        str(item.get("directory_record_id")): item
        for item in previous
        if isinstance(item, dict) and item.get("directory_record_id")
    }

    provider = LangSearchProvider(
        timeout=args.timeout,
        min_interval=args.min_interval,
    )

    attempted_this_run = 0
    succeeded_this_run = 0
    failed_this_run = 0

    for row in rows:
        if not isinstance(row, dict):
            continue

        record_id = str(row.get("directory_record_id") or "").strip()
        if not record_id:
            continue

        existing = by_id.get(record_id)
        if existing and existing.get("status") == "OK":
            continue

        if args.limit and attempted_this_run >= args.limit:
            break

        query = targeted_query(row)
        attempted_this_run += 1

        print(
            f"[{attempted_this_run}] {record_id} "
            f"{row.get("company", "")} — {row.get("city", "")}, "
            f"{row.get("province", "")}",
            flush=True,
        )

        try:
            response = provider.search(
                query,
                limit=args.results_per_query,
            )

            raw_results = response.get("results") or []
            candidate_results = [
                item for item in raw_results
                if not excluded(item.get("url"))
            ]

            result = {
                "directory_record_id": record_id,
                "directory_index": row.get("directory_index"),
                "company": row.get("company", ""),
                "city": row.get("city", ""),
                "province": row.get("province", ""),
                "website_status": row.get("website_status", ""),
                "existing_candidate_website": row.get("candidate_website", ""),
                "query": query,
                "provider": "langsearch",
                "provider_log_id": response.get("log_id"),
                "status": "OK",
                "search_results": raw_results,
                "candidate_results": candidate_results,
                "candidate_count": len(candidate_results),
            }
            succeeded_this_run += 1

        except (LangSearchError, ValueError) as exc:
            result = {
                "directory_record_id": record_id,
                "directory_index": row.get("directory_index"),
                "company": row.get("company", ""),
                "city": row.get("city", ""),
                "province": row.get("province", ""),
                "website_status": row.get("website_status", ""),
                "existing_candidate_website": row.get("candidate_website", ""),
                "query": query,
                "provider": "langsearch",
                "status": "ERROR",
                "error": str(exc),
                "search_results": [],
                "candidate_results": [],
                "candidate_count": 0,
            }
            failed_this_run += 1

        by_id[record_id] = result

        ordered = sorted(
            by_id.values(),
            key=lambda item: int(item.get("directory_index") or 0),
        )

        atomic_json(results_path, ordered)

        atomic_json(state_path, {
            "input_records": len(rows),
            "completed_ok": sum(x.get("status") == "OK" for x in ordered),
            "errors": sum(x.get("status") == "ERROR" for x in ordered),
            "attempted_this_run": attempted_this_run,
            "succeeded_this_run": succeeded_this_run,
            "failed_this_run": failed_this_run,
            "remaining": len(rows) - sum(x.get("status") == "OK" for x in ordered),
        })

    final = sorted(
        by_id.values(),
        key=lambda item: int(item.get("directory_index") or 0),
    )

    summary = {
        "input_records": len(rows),
        "records_saved": len(final),
        "completed_ok": sum(x.get("status") == "OK" for x in final),
        "errors": sum(x.get("status") == "ERROR" for x in final),
        "with_candidates": sum(
            x.get("status") == "OK" and x.get("candidate_count", 0) > 0
            for x in final
        ),
        "remaining": len(rows) - sum(x.get("status") == "OK" for x in final),
    }

    atomic_json(args.output_dir / "summary.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
