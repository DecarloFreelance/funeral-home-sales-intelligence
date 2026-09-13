#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

import requests


API_URL = "https://api.langsearch.com/v1/web-search"


class RateLimitError(RuntimeError):
    def __init__(
        self,
        message,
        retry_after=None,
        rate_headers=None,
    ):
        super().__init__(message)
        self.retry_after = retry_after
        self.rate_headers = rate_headers or {}


def load(path):
    return json.loads(
        Path(path).read_text(
            encoding="utf-8"
        )
    )


def atomic_json(path, value):
    path = Path(path)

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    tmp = path.with_suffix(
        path.suffix + ".tmp"
    )

    tmp.write_text(
        json.dumps(
            value,
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )

    os.replace(
        tmp,
        path,
    )


def host(value):
    value = str(
        value or ""
    ).strip()

    if not value:
        return ""

    if "://" not in value:
        value = (
            "https://"
            + value
        )

    try:
        hostname = (
            urlsplit(value).hostname
            or ""
        )
    except ValueError:
        return ""

    hostname = (
        hostname
        .lower()
        .rstrip(".")
    )

    if hostname.startswith(
        "www."
    ):
        hostname = hostname[4:]

    return hostname


def clean_query_piece(value):
    return re.sub(
        r"\s+",
        " ",
        str(value or ""),
    ).strip()


def quoted(value):
    value = clean_query_piece(
        value
    )

    if not value:
        return ""

    value = value.replace(
        '"',
        " ",
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    ).strip()

    return f'"{value}"'


def target_query(row, branch):
    reason = row["reason"]

    company = clean_query_piece(
        row.get("company")
    )

    city = clean_query_piece(
        row.get("city")
    )

    province = clean_query_piece(
        row.get("province")
    )

    domain = ""

    if branch:
        domain = host(
            branch.get("domain")
            or branch.get("website")
        )

    if (
        reason
        == "shared_domain_no_safe_contact_attribution"
    ):
        parts = [
            (
                f"site:{domain}"
                if domain
                else ""
            ),
            quoted(company),
            quoted(city),
            "contact",
            "staff",
            "funeral",
        ]

        purpose = (
            "branch_contact_attribution"
        )

    elif (
        reason
        == "verified_website_no_contact_found"
    ):
        parts = [
            (
                f"site:{domain}"
                if domain
                else ""
            ),
            quoted(company),
            quoted(city),
            "contact",
            "staff",
            "email",
            "phone",
        ]

        purpose = (
            "contact_discovery"
        )

    elif (
        reason
        == "no_verified_website"
    ):
        parts = [
            quoted(company),
            quoted(city),
            province,
            "Canada",
            "funeral home",
            "official website",
        ]

        purpose = (
            "website_discovery"
        )

    else:
        raise ValueError(
            f"unsupported reason: {reason}"
        )

    query = " ".join(
        part
        for part in parts
        if part
    )

    return (
        purpose,
        query,
        domain,
    )


def normalize_result(item):
    if not isinstance(
        item,
        dict,
    ):
        return None

    url = str(
        item.get("url")
        or ""
    ).strip()

    if not url:
        return None

    return {
        "name":
            item.get("name"),
        "url":
            url,
        "domain":
            host(url),
        "display_url":
            item.get(
                "displayUrl"
            ),
        "snippet":
            item.get("snippet"),
        "date_published":
            item.get(
                "datePublished"
            ),
        "date_last_crawled":
            item.get(
                "dateLastCrawled"
            ),
    }


def perform_search(
    session,
    api_key,
    query,
    timeout,
):
    response = session.post(
        API_URL,
        headers={
            "Authorization":
                f"Bearer {api_key}",
            "Content-Type":
                "application/json",
        },
        json={
            "query":
                query,
            "freshness":
                "noLimit",
            "summary":
                False,
            "count":
                10,
        },
        timeout=timeout,
    )

    status_code = (
        response.status_code
    )

    if status_code == 429:
        retry_after = response.headers.get(
            "Retry-After"
        )

        rate_headers = {
            key: value
            for key, value in response.headers.items()
            if (
                "rate" in key.casefold()
                or "limit" in key.casefold()
                or "retry" in key.casefold()
            )
        }

        body_preview = (
            response.text or ""
        )[:1000]

        raise RateLimitError(
            "LangSearch HTTP 429"
            + (
                f"; Retry-After={retry_after}"
                if retry_after
                else ""
            )
            + (
                f"; body={body_preview}"
                if body_preview
                else ""
            ),
            retry_after=retry_after,
            rate_headers=rate_headers,
        )

    response.raise_for_status()

    payload = response.json()

    if payload.get("code") not in (
        0,
        200,
        None,
    ):
        raise RuntimeError(
            "LangSearch API error: "
            + json.dumps(
                payload,
                ensure_ascii=False,
            )[:1000]
        )

    values = (
        payload
        .get("data", {})
        .get("webPages", {})
        .get("value", [])
    )

    results = []

    for item in values:
        result = normalize_result(
            item
        )

        if result:
            results.append(
                result
            )

    return {
        "http_status":
            status_code,
        "code":
            payload.get("code"),
        "msg":
            payload.get("msg"),
        "log_id":
            payload.get("log_id"),
        "results":
            results,
    }


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--unresolved",
        required=True,
    )

    parser.add_argument(
        "--branches",
        required=True,
    )

    parser.add_argument(
        "--outdir",
        required=True,
    )

    parser.add_argument(
        "--delay",
        type=float,
        default=1.05,
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
    )

    parser.add_argument(
        "--max-records",
        type=int,
        default=0,
    )

    args = parser.parse_args()

    api_key = os.environ.get(
        "LANGSEARCH_API_KEY"
    )

    if not api_key:
        raise SystemExit(
            "LANGSEARCH_API_KEY not set"
        )

    unresolved = load(
        args.unresolved
    )

    branches = load(
        args.branches
    )

    branch_by_id = {
        row[
            "directory_record_id"
        ]: row
        for row in branches
    }

    supported = {
        "no_verified_website",
        "shared_domain_no_safe_contact_attribution",
        "verified_website_no_contact_found",
    }

    targets = [
        row
        for row in unresolved
        if row.get("reason")
        in supported
    ]

    priority = {
        "shared_domain_no_safe_contact_attribution":
            0,
        "verified_website_no_contact_found":
            1,
        "no_verified_website":
            2,
    }

    targets.sort(
        key=lambda row: (
            priority[
                row["reason"]
            ],
            row[
                "directory_record_id"
            ],
        )
    )

    outdir = Path(
        args.outdir
    )

    outdir.mkdir(
        parents=True,
        exist_ok=True,
    )

    results_path = (
        outdir
        / "search_results.json"
    )

    state_path = (
        outdir
        / "state.json"
    )

    summary_path = (
        outdir
        / "summary.json"
    )

    if results_path.exists():
        saved = load(
            results_path
        )

        if not isinstance(
            saved,
            list,
        ):
            raise SystemExit(
                "existing search_results.json "
                "is not a list"
            )

    else:
        saved = []

    saved_by_id = {
        row[
            "directory_record_id"
        ]: row
        for row in saved
        if isinstance(
            row,
            dict,
        )
        and row.get(
            "directory_record_id"
        )
    }

    session = requests.Session()

    attempted_this_run = 0
    rate_limited = False
    rate_limit_info = None

    for index, target in enumerate(
        targets,
        start=1,
    ):
        record_id = target[
            "directory_record_id"
        ]

        existing = saved_by_id.get(
            record_id
        )

        if (
            existing
            and existing.get(
                "status"
            ) == "OK"
        ):
            continue

        if (
            args.max_records > 0
            and attempted_this_run
            >= args.max_records
        ):
            break

        branch = branch_by_id.get(
            record_id
        )

        purpose, query, domain = (
            target_query(
                target,
                branch,
            )
        )

        query_hash = hashlib.sha256(
            query.encode(
                "utf-8"
            )
        ).hexdigest()

        print(
            f"[{index}/{len(targets)}] "
            f"{record_id} "
            f"{target['reason']}"
        )

        print(
            "  query:",
            query,
        )

        attempted_this_run += 1

        try:
            response = perform_search(
                session,
                api_key,
                query,
                args.timeout,
            )

            row = {
                **target,
                "purpose":
                    purpose,
                "existing_domain":
                    domain,
                "query":
                    query,
                "query_sha256":
                    query_hash,
                "status":
                    "OK",
                "result_count":
                    len(
                        response[
                            "results"
                        ]
                    ),
                "results":
                    response[
                        "results"
                    ],
                "langsearch_log_id":
                    response[
                        "log_id"
                    ],
                "langsearch_code":
                    response[
                        "code"
                    ],
                "langsearch_msg":
                    response[
                        "msg"
                    ],
            }

            print(
                "  results:",
                row[
                    "result_count"
                ],
            )

        except RateLimitError as exc:
            row = {
                **target,
                "purpose":
                    purpose,
                "existing_domain":
                    domain,
                "query":
                    query,
                "query_sha256":
                    query_hash,
                "status":
                    "RATE_LIMITED",
                "error":
                    str(exc),
                "retry_after":
                    exc.retry_after,
                "rate_limit_headers":
                    exc.rate_headers,
                "result_count":
                    0,
                "results":
                    [],
            }

            rate_limited = True
            rate_limit_info = {
                "directory_record_id":
                    record_id,
                "retry_after":
                    exc.retry_after,
                "rate_limit_headers":
                    exc.rate_headers,
                "error":
                    str(exc),
            }

            print(
                "  RATE LIMITED:",
                row["error"],
            )

        except Exception as exc:
            row = {
                **target,
                "purpose":
                    purpose,
                "existing_domain":
                    domain,
                "query":
                    query,
                "query_sha256":
                    query_hash,
                "status":
                    "ERROR",
                "error":
                    f"{type(exc).__name__}: {exc}",
                "result_count":
                    0,
                "results":
                    [],
            }

            print(
                "  ERROR:",
                row["error"],
            )

        saved_by_id[
            record_id
        ] = row

        ordered = [
            saved_by_id[
                target_row[
                    "directory_record_id"
                ]
            ]
            for target_row
            in targets
            if target_row[
                "directory_record_id"
            ]
            in saved_by_id
        ]

        atomic_json(
            results_path,
            ordered,
        )

        completed_ok = sum(
            row.get(
                "status"
            ) == "OK"
            for row in ordered
        )

        errors = sum(
            row.get(
                "status"
            ) == "ERROR"
            for row in ordered
        )

        state = {
            "targets":
                len(targets),
            "saved":
                len(ordered),
            "completed_ok":
                completed_ok,
            "errors":
                errors,
            "remaining":
                len(targets)
                - completed_ok,
            "attempted_this_run":
                attempted_this_run,
        }

        atomic_json(
            state_path,
            state,
        )

        if rate_limited:
            print()
            print(
                "CIRCUIT BREAKER: "
                "LangSearch returned HTTP 429."
            )
            print(
                "Checkpoint saved. "
                "Stopping API requests immediately."
            )

            if rate_limit_info:
                print(
                    json.dumps(
                        rate_limit_info,
                        indent=2,
                        ensure_ascii=False,
                    )
                )

            break

        if row[
            "status"
        ] == "OK":
            time.sleep(
                max(
                    args.delay,
                    0.0,
                )
            )

        else:
            # Keep errors restartable but avoid
            # hammering an API that may be
            # rate-limiting the account.
            time.sleep(
                max(
                    args.delay,
                    1.25,
                )
            )

    final_rows = [
        saved_by_id[
            target[
                "directory_record_id"
            ]
        ]
        for target in targets
        if target[
            "directory_record_id"
        ]
        in saved_by_id
    ]

    status_counts = Counter(
        row.get(
            "status",
            "UNKNOWN",
        )
        for row in final_rows
    )

    reason_counts = Counter(
        row.get(
            "reason",
            "UNKNOWN",
        )
        for row in final_rows
        if row.get(
            "status"
        ) == "OK"
    )

    with_results = sum(
        row.get(
            "status"
        ) == "OK"
        and row.get(
            "result_count",
            0,
        ) > 0
        for row in final_rows
    )

    unique_candidate_domains = {
        result[
            "domain"
        ]
        for row in final_rows
        if row.get(
            "status"
        ) == "OK"
        for result in row.get(
            "results",
            []
        )
        if result.get(
            "domain"
        )
    }

    completed_ok_ids = {
        row[
            "directory_record_id"
        ]
        for row in final_rows
        if row.get(
            "status"
        ) == "OK"
    }

    target_ids = {
        row[
            "directory_record_id"
        ]
        for row in targets
    }

    summary = {
        "target_records":
            len(targets),
        "target_reason_counts":
            dict(
                Counter(
                    row["reason"]
                    for row in targets
                )
            ),
        "records_saved":
            len(final_rows),
        "status_counts":
            dict(
                status_counts
            ),
        "completed_ok":
            len(
                completed_ok_ids
            ),
        "remaining":
            len(
                target_ids
                - completed_ok_ids
            ),
        "with_results":
            with_results,
        "unique_candidate_domains":
            len(
                unique_candidate_domains
            ),
        "completed_reason_counts":
            dict(
                reason_counts
            ),
        "restartable":
            True,
        "rate_limited":
            rate_limited,
        "rate_limit_info":
            rate_limit_info,
    }

    atomic_json(
        summary_path,
        summary,
    )

    print()
    print(
        "===== FINAL SUMMARY ====="
    )

    print(
        json.dumps(
            summary,
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
