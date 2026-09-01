#!/usr/bin/env python3
"""Verify cached LangSearch candidates against bounded first-party fetches."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
from pathlib import Path
from urllib.parse import urlsplit

from audit_merge_falconer_v7 import write_json
from verify_955_websites import company_tokens, normalize, verify_record

HOST_DENY_SUBSTRINGS = (
    "obituar",
    "infoisinfo",
    "canada-advisor",
    "canadacompanies",
    "directory",
)
WEAK_IDENTITY_TOKENS = {"first"}


def identity_tokens(company: str) -> list[str]:
    available = company_tokens(company)
    ordered = [word for word in normalize(company).split() if word in available and len(word) >= 4]
    return ordered[:2]


def identity_domain_label(host: str) -> str:
    """Return the registrable-looking identity label, never an arbitrary subdomain.

    This deliberately fails closed for deceptive hosts such as
    heritagefuneralcentre.ca.domreaper.com: the identity label is
    domreaper, not heritagefuneralcentre.
    """
    host = host.casefold().strip().rstrip(".")
    if host.startswith("www."):
        host = host[4:]

    labels = [label for label in host.split(".") if label]

    if len(labels) < 2:
        return ""

    # Common Canadian second-level namespaces, e.g. example.on.ca.
    if (
        len(labels) >= 3
        and labels[-1] == "ca"
        and labels[-2]
        in {
            "ab", "bc", "mb", "nb", "nf", "nl", "ns",
            "nt", "nu", "on", "pe", "qc", "sk", "yk",
        }
    ):
        return labels[-3]

    return labels[-2]


def domain_supports_company(host: str, company: str) -> bool:
    label = "".join(
        ch
        for ch in identity_domain_label(host)
        if ch.isalnum()
    )

    if not label:
        return False

    supported = {
        token
        for token in identity_tokens(company)
        if token in label
    }

    return bool(supported - WEAK_IDENTITY_TOKENS)


def enforce_first_party(result: dict) -> dict:
    if result.get("status") not in {"VERIFIED", "VERIFIED_HIGH"}:
        return result
    evidence = result.get("evidence") or {}
    domain_supported = float(evidence.get("host_overlap") or 0) > 0
    host_value = str(evidence.get("host") or "").casefold()
    token_supported = domain_supports_company(
        host_value,
        result.get("company", ""),
    )
    if not any(marker in host_value for marker in HOST_DENY_SUBSTRINGS) and (domain_supported or token_supported):
        website = str(result.get("website") or "")
        parts = urlsplit(website)
        canonical = f"{parts.scheme}://{parts.netloc}/" if parts.scheme and parts.netloc else website
        return {**result, "website": canonical, "domain": parts.hostname or result.get("domain", "")}
    return {**result, "status": "REVIEW", "website": "", "domain": "",
            "confidence": "REVIEW", "first_party_guard": "rejected_no_domain_identity_support"}


def first_party_candidates(row: dict, candidates: list[dict]) -> list[dict]:
    selected = []
    for candidate in candidates:
        try:
            host = (urlsplit(str(candidate.get("url") or "")).hostname or "").casefold()
        except ValueError:
            continue
        if any(marker in host for marker in HOST_DENY_SUBSTRINGS):
            continue
        if domain_supports_company(
            host,
            row.get("company", ""),
        ):
            selected.append(candidate)
    return selected


def load_reconciled_evidence(path: Path, by_id: dict[str, dict]) -> dict[str, dict]:
    """Load previously fetched bounded evidence only when it remains verifiable.

    This is intended for transient fetch discrepancies.  It does not promote raw
    search results: the stored row must contain a successful verification fetch
    and must still pass the current first-party guard.
    """
    rows = json.loads(path.read_text(encoding="utf-8"))
    reconciled = {}
    for stored in rows:
        record_id = stored.get("directory_record_id")
        evidence = stored.get("evidence") or {}
        guarded = enforce_first_party(stored)
        if (
            record_id not in by_id
            or guarded.get("status") not in {"VERIFIED", "VERIFIED_HIGH"}
            or not evidence.get("fetch_ok")
            or evidence.get("status_code") != 200
            or not evidence.get("verified")
        ):
            continue
        reconciled[record_id] = {
            **guarded,
            "reconciliation_provenance": {
                "kind": "stored_bounded_verification_evidence",
                "source_path": str(path),
                "current_first_party_guard_passed": True,
            },
        }
    return reconciled


def verify(queue_path: Path, search_path: Path, output: Path, *, workers: int = 8,
           top_candidates: int = 3, timeout: float = 12, max_bytes: int = 600000,
           limit: int = 0, audit_only: bool = False, reverify_review: bool = False,
           reconcile_evidence: Path | None = None) -> dict:
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    searches = json.loads(search_path.read_text(encoding="utf-8"))
    by_id = {row["directory_record_id"]: row for row in queue}
    prior_path = output / "verified_websites.json"
    prior = json.loads(prior_path.read_text(encoding="utf-8")) if prior_path.is_file() else []
    results = {row["directory_record_id"]: enforce_first_party(row) for row in prior}
    if reconcile_evidence is not None:
        results.update(load_reconciled_evidence(reconcile_evidence, by_id))
    if reverify_review:
        results = {key: row for key, row in results.items() if row.get("status") in {"VERIFIED", "VERIFIED_HIGH"}}
    pending = []
    for search in searches:
        record_id = search.get("directory_record_id")
        if search.get("status") != "OK" or record_id not in by_id or record_id in results:
            continue
        row = by_id[record_id]
        pending.append((row, {**search, "candidate_results": first_party_candidates(row, search.get("results") or [])}))
    if limit:
        pending = pending[:limit]
    if audit_only:
        pending = []

    def run(item):
        row, search = item
        return enforce_first_party(verify_record(row, search, top_candidates, timeout, max_bytes))

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        for row in executor.map(run, pending):
            results[row["directory_record_id"]] = row
            write_json(prior_path, sorted(results.values(), key=lambda x: int(x.get("directory_index") or 0)))

    ordered = sorted(results.values(), key=lambda x: int(x.get("directory_index") or 0))
    write_json(prior_path, ordered)
    verified = [row for row in ordered if row.get("status") in {"VERIFIED", "VERIFIED_HIGH"}]
    review = [row for row in ordered if row.get("status") in {"REVIEW", "UNRESOLVED"}]
    source = [{"directory_record_id": row["directory_record_id"], "company": row["company"],
               "city": row["city"], "province": row["province"], "website": row["website"],
               "website_status": "selected", "record_type": "directory_verified",
               "source": "langsearch_v2_plus_first_party_verification",
               "verification_confidence": row["confidence"],
               "verification_score": row["verification_score"]} for row in verified]
    summary = {"cached_search_records": len(searches), "verified_records": len(verified),
               "review_or_unresolved": len(review), "completed_records": len(ordered),
               "network_fetches_are_bounded": True, "crm_writes": 0, "outreach_actions": 0}
    write_json(output / "verified_source.json", source)
    write_json(output / "review_queue.json", review)
    write_json(output / "summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--search-results", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--top-candidates", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=12)
    parser.add_argument("--max-bytes", type=int, default=600000)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--reverify-review", action="store_true")
    parser.add_argument("--reconcile-evidence", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.queue, args.search_results, args.output_dir,
                            workers=args.workers, top_candidates=args.top_candidates,
                            timeout=args.timeout, max_bytes=args.max_bytes, limit=args.limit,
                            audit_only=args.audit_only, reverify_review=args.reverify_review,
                            reconcile_evidence=args.reconcile_evidence), indent=2))


if __name__ == "__main__":
    main()
