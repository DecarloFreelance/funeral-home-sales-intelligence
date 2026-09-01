#!/usr/bin/env python3

import argparse
import html as html_lib
import json
import os
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit

from bs4 import BeautifulSoup


GENERIC_COMPANY_WORDS = {
    "funeral",
    "funerals",
    "home",
    "homes",
    "service",
    "services",
    "chapel",
    "chapels",
    "cremation",
    "crematorium",
    "cemetery",
    "memorial",
    "centre",
    "center",
    "limited",
    "ltd",
    "inc",
    "incorporated",
    "family",
    "and",
    "the",
    "of",
    "care",
}


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


def normalize(value):
    value = str(
        value or ""
    )

    value = unicodedata.normalize(
        "NFKD",
        value,
    )

    value = "".join(
        char
        for char in value
        if not unicodedata.combining(
            char
        )
    )

    value = value.casefold()

    value = re.sub(
        r"[^a-z0-9]+",
        " ",
        value,
    )

    return re.sub(
        r"\s+",
        " ",
        value,
    ).strip()


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


def path_of(value):
    value = str(
        value or ""
    ).strip()

    if not value:
        return "/"

    if "://" not in value:
        value = (
            "https://"
            + value
        )

    try:
        path = (
            urlsplit(value).path
            or "/"
        )
    except ValueError:
        return "/"

    path = re.sub(
        r"/+",
        "/",
        path,
    )

    if not path.startswith("/"):
        path = "/" + path

    return path.rstrip("/") or "/"


def page_url(page):
    if not isinstance(
        page,
        dict,
    ):
        return ""

    for key in (
        "final_url",
        "url",
        "source_url",
        "website",
        "homepage",
    ):
        value = page.get(key)

        if (
            isinstance(value, str)
            and value.strip()
        ):
            return value.strip()

    return ""


def page_text(page):
    if not isinstance(
        page,
        dict,
    ):
        return ""

    chunks = []

    for key in (
        "html",
        "content",
        "text",
        "body",
        "title",
    ):
        value = page.get(key)

        if (
            isinstance(value, str)
            and value.strip()
        ):
            chunks.append(value)

    raw = "\n".join(
        chunks
    )

    if not raw:
        return ""

    if re.search(
        r"<(?:html|body|div|p|span|section)\b",
        raw,
        re.I,
    ):
        try:
            soup = BeautifulSoup(
                raw,
                "html.parser",
            )

            for tag in soup(
                [
                    "script",
                    "style",
                    "noscript",
                    "svg",
                ]
            ):
                tag.decompose()

            raw = soup.get_text(
                "\n",
                strip=True,
            )
        except Exception:
            pass

    return normalize(
        html_lib.unescape(
            raw
        )
    )


def distinctive_company_tokens(
    company
):
    tokens = [
        token
        for token in normalize(
            company
        ).split()
        if (
            token
            not in GENERIC_COMPANY_WORDS
            and len(token) >= 4
        )
    ]

    return set(
        tokens
    )


def evidence_key(item):
    if not isinstance(
        item,
        dict,
    ):
        return (
            str(item),
            "",
        )

    return (
        str(
            item.get("value")
            or item.get("name")
            or ""
        ),
        str(
            item.get("title")
            or ""
        ),
    )


def evidence_url(item):
    if not isinstance(
        item,
        dict,
    ):
        return ""

    return str(
        item.get(
            "source_url"
        )
        or ""
    ).strip()


def candidate_score(
    branch,
    all_branches,
    source_url,
    source_text,
):
    score = 0
    reasons = []

    branch_city = normalize(
        branch.get("city")
    )

    branch_province = normalize(
        branch.get("province")
    )

    branch_company = normalize(
        branch.get("company")
    )

    source_url_norm = normalize(
        source_url
    )

    mapping_path = path_of(
        branch.get("website")
    )

    source_path = path_of(
        source_url
    )

    # Strongest evidence:
    # specific verified branch URL/path.
    if (
        mapping_path != "/"
        and (
            source_path == mapping_path
            or source_path.startswith(
                mapping_path + "/"
            )
        )
    ):
        score += 10
        reasons.append(
            "verified_branch_path"
        )

    # City evidence is useful only when the
    # source page does not mention multiple
    # branch cities from the same domain.
    cities_present = set()

    for other in all_branches:
        city = normalize(
            other.get("city")
        )

        if (
            city
            and (
                city in source_text
                or city in source_url_norm
            )
        ):
            cities_present.add(
                city
            )

    if (
        branch_city
        and branch_city
        in cities_present
        and len(
            cities_present
        ) == 1
    ):
        score += 7
        reasons.append(
            "unique_branch_city"
        )

    # If different brands/names share one
    # corporate domain, distinctive name
    # evidence can identify a branch.
    branch_tokens = (
        distinctive_company_tokens(
            branch_company
        )
    )

    if branch_tokens:
        other_token_sets = [
            distinctive_company_tokens(
                other.get("company")
            )
            for other in all_branches
            if (
                other[
                    "directory_record_id"
                ]
                != branch[
                    "directory_record_id"
                ]
            )
        ]

        unique_tokens = {
            token
            for token in branch_tokens
            if not any(
                token in other_tokens
                for other_tokens
                in other_token_sets
            )
        }

        matched_unique = {
            token
            for token in unique_tokens
            if token in source_text
        }

        if len(
            matched_unique
        ) >= 2:
            score += 6
            reasons.append(
                "unique_company_tokens"
            )

        elif len(
            matched_unique
        ) == 1:
            score += 3
            reasons.append(
                "one_unique_company_token"
            )

    # Province alone is deliberately weak.
    if (
        branch_province
        and branch_province
        in source_text
    ):
        score += 1
        reasons.append(
            "province"
        )

    return (
        score,
        reasons,
    )


def attribute_item(
    item,
    branches,
    page_by_url,
    page_text_by_url=None,
):
    source_url = evidence_url(
        item
    )

    source_page = (
        page_by_url.get(
            source_url
        )
    )

    if page_text_by_url is not None:
        source_text = page_text_by_url.get(source_url, "")
    else:
        source_text = page_text(source_page) if source_page else ""

    ranked = []

    for branch in branches:
        score, reasons = (
            candidate_score(
                branch,
                branches,
                source_url,
                source_text,
            )
        )

        ranked.append(
            {
                "directory_record_id":
                    branch[
                        "directory_record_id"
                    ],
                "score":
                    score,
                "reasons":
                    reasons,
            }
        )

    ranked.sort(
        key=lambda row: (
            -row["score"],
            row[
                "directory_record_id"
            ],
        )
    )

    if not ranked:
        return (
            None,
            {
                "reason":
                    "no_branch_candidates",
                "ranking":
                    [],
            },
        )

    best = ranked[0]

    second_score = (
        ranked[1]["score"]
        if len(ranked) > 1
        else -1
    )

    # Require strong evidence and a clear
    # winner. This intentionally favors
    # precision over recall.
    if (
        best["score"] >= 6
        and (
            best["score"]
            - second_score
        ) >= 2
    ):
        return (
            best[
                "directory_record_id"
            ],
            {
                "reason":
                    "branch_attributed",
                "winning_score":
                    best["score"],
                "winning_reasons":
                    best["reasons"],
                "runner_up_score":
                    second_score,
            },
        )

    return (
        None,
        {
            "reason":
                "shared_domain_ambiguous",
            "ranking":
                ranked[:5],
        },
    )


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--master",
        required=True,
    )

    parser.add_argument(
        "--mappings",
        required=True,
    )

    parser.add_argument(
        "--contacts",
        required=True,
    )

    parser.add_argument(
        "--domain-contacts",
        required=True,
    )

    parser.add_argument(
        "--quarantine",
        required=True,
    )

    parser.add_argument(
        "--pages",
        required=True,
    )

    parser.add_argument(
        "--outdir",
        required=True,
    )

    args = parser.parse_args()

    master = load(
        args.master
    )

    mappings = load(
        args.mappings
    )

    contacts = load(
        args.contacts
    )

    domain_contacts = load(
        args.domain_contacts
    )

    quarantine = load(
        args.quarantine
    )

    pages = load(
        args.pages
    )

    if len(master) != 955:
        raise SystemExit(
            f"expected 955 master rows; got {len(master)}"
        )

    # The verified mapping set is intentionally versioned and may shrink
    # after a legacy re-check quarantines stale/third-party hosts (for
    # example, the current v2 crawl has 254 verified rows versus the
    # original 530).  Require a non-empty, internally consistent set rather
    # than a historical hard-coded count so attribution can run on the
    # latest verifier output without silently accepting malformed input.
    if not mappings:
        raise SystemExit("expected at least one verified mapping")

    mapping_ids = [row.get("directory_record_id") for row in mappings]
    if any(not value for value in mapping_ids) or len(set(mapping_ids)) != len(mapping_ids):
        raise SystemExit("verified mappings must have unique directory_record_id values")

    quarantine_ids = {
        row[
            "directory_record_id"
        ]
        for row in quarantine
    }

    mapping_by_id = {
        row[
            "directory_record_id"
        ]: row
        for row in mappings
    }

    contact_by_id = {
        row[
            "directory_record_id"
        ]: row
        for row in contacts
    }

    branches_by_domain = (
        defaultdict(list)
    )

    for row in mappings:
        if (
            row[
                "directory_record_id"
            ]
            in quarantine_ids
        ):
            continue

        domain = host(
            row.get("domain")
            or row.get("website")
        )

        branches_by_domain[
            domain
        ].append(
            row
        )

    domain_contact_by_domain = {
        host(
            row.get("domain")
        ): row
        for row in domain_contacts
    }

    page_by_url = {}

    for page in pages:
        url = page_url(
            page
        )

        if url:
            page_by_url[
                url
            ] = page

    # Normalize each crawled page once.  Shared-domain evidence can reference
    # the same page for many extracted values; recomputing BeautifulSoup text
    # for every value made attribution needlessly quadratic and could prevent
    # the corrected 254-row mapping set from completing within an operator run.
    page_text_by_url = {
        url: page_text(page)
        for url, page in page_by_url.items()
    }

    output_by_id = {}

    unattributed_by_domain = (
        defaultdict(
            lambda: {
                "emails": [],
                "phones": [],
                "staff": [],
                "decision_makers": [],
            }
        )
    )

    attribution_audit = []

    # Start each accepted verified business
    # with an empty branch-safe record.
    for record_id, mapping in (
        mapping_by_id.items()
    ):
        if record_id in quarantine_ids:
            continue

        domain = host(
            mapping.get("domain")
            or mapping.get("website")
        )

        shared = (
            len(
                branches_by_domain[
                    domain
                ]
            ) > 1
        )

        output_by_id[
            record_id
        ] = {
            "directory_record_id":
                record_id,
            "company":
                mapping.get(
                    "company"
                ),
            "city":
                mapping.get(
                    "city"
                ),
            "province":
                mapping.get(
                    "province"
                ),
            "website":
                mapping.get(
                    "website"
                ),
            "domain":
                domain,
            "shared_domain":
                shared,
            "emails": [],
            "phones": [],
            "staff": [],
            "decision_makers": [],
            "attribution_status":
                (
                    "branch_attribution_required"
                    if shared
                    else "direct_domain"
                ),
        }

    # Non-shared domains are safe to retain
    # exactly as V3 business-domain evidence.
    for record_id, record in (
        contact_by_id.items()
    ):
        if record_id not in output_by_id:
            continue

        domain = output_by_id[
            record_id
        ]["domain"]

        if len(
            branches_by_domain[
                domain
            ]
        ) != 1:
            continue

        target = output_by_id[
            record_id
        ]

        for field in (
            "emails",
            "phones",
            "staff",
            "decision_makers",
        ):
            target[field] = list(
                record.get(
                    field,
                    [],
                )
            )

        target[
            "attribution_status"
        ] = "direct_domain"

    # Shared domains are re-attributed from
    # domain evidence rather than copied to
    # every branch.
    for domain, branches in (
        branches_by_domain.items()
    ):
        if len(branches) <= 1:
            continue

        evidence = (
            domain_contact_by_domain.get(
                domain,
                {}
            )
        )

        for field in (
            "emails",
            "phones",
            "staff",
        ):
            seen = set()

            for item in evidence.get(
                field,
                [],
            ):
                key = evidence_key(
                    item
                )

                if key in seen:
                    continue

                seen.add(
                    key
                )

                record_id, audit = (
                    attribute_item(
                        item,
                        branches,
                        page_by_url,
                        page_text_by_url,
                    )
                )

                audit_row = {
                    "domain":
                        domain,
                    "field":
                        field,
                    "evidence_key":
                        key,
                    "source_url":
                        evidence_url(
                            item
                        ),
                    **audit,
                }

                if record_id:
                    output_by_id[
                        record_id
                    ][field].append(
                        item
                    )

                    if (
                        field == "staff"
                        and item.get(
                            "decision_maker"
                        )
                    ):
                        output_by_id[
                            record_id
                        ][
                            "decision_makers"
                        ].append(
                            item
                        )

                    audit_row[
                        "directory_record_id"
                    ] = record_id

                else:
                    unattributed_by_domain[
                        domain
                    ][field].append(
                        item
                    )

                    if (
                        field == "staff"
                        and item.get(
                            "decision_maker"
                        )
                    ):
                        unattributed_by_domain[
                            domain
                        ][
                            "decision_makers"
                        ].append(
                            item
                        )

                attribution_audit.append(
                    audit_row
                )

    branch_rows = []

    for record_id in sorted(
        output_by_id
    ):
        row = output_by_id[
            record_id
        ]

        for field in (
            "emails",
            "phones",
            "staff",
            "decision_makers",
        ):
            unique = {}
            for item in row[field]:
                unique[
                    evidence_key(
                        item
                    )
                ] = item

            row[field] = list(
                unique.values()
            )

        row["email_count"] = len(
            row["emails"]
        )

        row["phone_count"] = len(
            row["phones"]
        )

        row["staff_count"] = len(
            row["staff"]
        )

        row[
            "decision_maker_count"
        ] = len(
            row[
                "decision_makers"
            ]
        )

        row[
            "has_attributed_contact"
        ] = bool(
            row["emails"]
            or row["phones"]
            or row["staff"]
        )

        if (
            row["shared_domain"]
            and row[
                "has_attributed_contact"
            ]
        ):
            row[
                "attribution_status"
            ] = (
                "shared_domain_attributed"
            )

        elif (
            row["shared_domain"]
            and not row[
                "has_attributed_contact"
            ]
        ):
            row[
                "attribution_status"
            ] = (
                "shared_domain_no_safe_attribution"
            )

        branch_rows.append(
            row
        )

    unattributed_rows = []

    for domain in sorted(
        unattributed_by_domain
    ):
        values = (
            unattributed_by_domain[
                domain
            ]
        )

        row = {
            "domain":
                domain,
            "business_ids": sorted(
                branch[
                    "directory_record_id"
                ]
                for branch
                in branches_by_domain[
                    domain
                ]
            ),
        }

        for field in (
            "emails",
            "phones",
            "staff",
            "decision_makers",
        ):
            unique = {}

            for item in values[
                field
            ]:
                unique[
                    evidence_key(
                        item
                    )
                ] = item

            row[field] = list(
                unique.values()
            )

            row[
                field + "_count"
            ] = len(
                row[field]
            )

        if (
            row["emails"]
            or row["phones"]
            or row["staff"]
        ):
            unattributed_rows.append(
                row
            )

    master_by_id = {
        row[
            "directory_record_id"
        ]: row
        for row in master
    }

    verified_ids = set(
        mapping_by_id
    )

    accepted_ids = set(
        output_by_id
    )

    unresolved = []

    for record_id in sorted(
        master_by_id
    ):
        master_row = (
            master_by_id[
                record_id
            ]
        )

        if record_id not in verified_ids:
            reason = (
                "no_verified_website"
            )

        elif record_id in quarantine_ids:
            reason = (
                "quarantined_website"
            )

        else:
            branch = (
                output_by_id[
                    record_id
                ]
            )

            if branch[
                "has_attributed_contact"
            ]:
                continue

            if branch[
                "shared_domain"
            ]:
                reason = (
                    "shared_domain_no_safe_contact_attribution"
                )
            else:
                reason = (
                    "verified_website_no_contact_found"
                )

        unresolved.append(
            {
                "directory_record_id":
                    record_id,
                "company":
                    master_row.get(
                        "company"
                    ),
                "city":
                    master_row.get(
                        "city"
                    ),
                "province":
                    master_row.get(
                        "province"
                    ),
                "website":
                    master_row.get(
                        "website"
                    ),
                "reason":
                    reason,
            }
        )

    reason_counts = Counter(
        row["reason"]
        for row in unresolved
    )

    direct_records = [
        row
        for row in branch_rows
        if not row[
            "shared_domain"
        ]
    ]

    shared_records = [
        row
        for row in branch_rows
        if row[
            "shared_domain"
        ]
    ]

    summary = {
        "master_records":
            len(master),
        "verified_mapping_records":
            len(mappings),
        "quarantined_records":
            len(quarantine_ids),
        "accepted_verified_records":
            len(branch_rows),
        "direct_domain_records":
            len(direct_records),
        "shared_domain_records":
            len(shared_records),
        "coverage_after_branch_attribution": {
            "with_email":
                sum(
                    row[
                        "email_count"
                    ] > 0
                    for row
                    in branch_rows
                ),
            "with_phone":
                sum(
                    row[
                        "phone_count"
                    ] > 0
                    for row
                    in branch_rows
                ),
            "with_named_staff":
                sum(
                    row[
                        "staff_count"
                    ] > 0
                    for row
                    in branch_rows
                ),
            "with_named_decision_maker":
                sum(
                    row[
                        "decision_maker_count"
                    ] > 0
                    for row
                    in branch_rows
                ),
            "with_any_attributed_contact":
                sum(
                    row[
                        "has_attributed_contact"
                    ]
                    for row
                    in branch_rows
                ),
        },
        "shared_domain_attribution": {
            "shared_records_with_safe_contact":
                sum(
                    row[
                        "has_attributed_contact"
                    ]
                    for row
                    in shared_records
                ),
            "shared_records_without_safe_contact":
                sum(
                    not row[
                        "has_attributed_contact"
                    ]
                    for row
                    in shared_records
                ),
            "domains_with_unattributed_contact_evidence":
                len(
                    unattributed_rows
                ),
        },
        "unresolved_records":
            len(unresolved),
        "unresolved_reason_counts":
            dict(
                sorted(
                    reason_counts.items()
                )
            ),
        "conservation": {
            "accepted_plus_quarantine_plus_no_verified_website":
                (
                    len(
                        accepted_ids
                    )
                    + len(
                        quarantine_ids
                    )
                    + len(
                        set(
                            master_by_id
                        )
                        - verified_ids
                    )
                ),
            "expected":
                len(master),
            "pass":
                (
                    len(
                        accepted_ids
                    )
                    + len(
                        quarantine_ids
                    )
                    + len(
                        set(
                            master_by_id
                        )
                        - verified_ids
                    )
                    == len(master)
                ),
        },
    }

    outdir = Path(
        args.outdir
    )

    atomic_json(
        outdir
        / "branch_contacts.json",
        branch_rows,
    )

    atomic_json(
        outdir
        / "domain_unattributed_contacts.json",
        unattributed_rows,
    )

    atomic_json(
        outdir
        / "attribution_audit.json",
        attribution_audit,
    )

    atomic_json(
        outdir
        / "unresolved_contact_queue.json",
        unresolved,
    )

    atomic_json(
        outdir
        / "summary.json",
        summary,
    )

    print(
        json.dumps(
            summary,
            indent=2,
            ensure_ascii=False,
        )
    )

    if not summary[
        "conservation"
    ]["pass"]:
        raise SystemExit(
            "955 conservation failed"
        )


if __name__ == "__main__":
    main()
