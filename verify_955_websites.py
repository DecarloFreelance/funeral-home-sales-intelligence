#!/usr/bin/env python3
"""Conservative official-website verification for the 955-directory project."""

import argparse
import concurrent.futures
import html
import json
import re
import threading
import unicodedata
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

from discovery.network_safety import public_web_url


DIRECTORY_DOMAINS = {
    "funeralhub.ca",
    "rentechdigital.com",
    "keepsakeguide.com",
    "funeralnavigator.com",
    "remembering.ca",
    "profilecanada.com",
    "canada247.info",
    "dnb.com",
    "bbb.org",
    "aubaine.ca",
    "funeralguide.co.uk",
    "yably.ca",
    "funerals.lk",
    "familyinfo.ca",
    "neverbounce.com",
    "listings.websites.ca",
    "waze.com",
    "rocketreach.co",
    "canpages.ca",
    "yellowpages.ca",
    "yelp.ca",
    "yelp.com",
    "allcanadachurches.com",
    "canada-advisor.com",
    "catalog-online.ca",
    "cdncompanies.com",
    "canadacompanies.net",
    "near-place.com",
    "maptons.com",
    "okredo.com",
    "legacy.com",
    "tributearchive.com",
    "echovita.com",
    "everloved.com",
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "youtube.com",
    "x.com",
    "twitter.com",
}

HOSTED_FIRST_PARTY = {
    "dignitymemorial.com",
    "arbormemorial.ca",
    "funeraltechweb.com",
    "frontrunnerpro.com",
}

GENERIC_TOKENS = {
    "the", "and", "of", "a", "an",
    "funeral", "funerals", "home", "homes",
    "service", "services",
    "cremation", "cremations", "crematorium",
    "burial", "chapel", "chapels",
    "centre", "center", "centres", "centers",
    "memorial", "family", "families",
    "limited", "ltd", "inc", "incorporated",
    "corporation", "corp", "co", "company",
    "community", "directors", "director",
    "care", "celebration", "reception",
}

FUNERAL_TERMS = {
    "funeral", "cremation", "crematorium",
    "burial", "obituary", "obituaries",
    "memorial", "chapel", "cemetery",
    "preplanning", "pre-planning",
    "funeral director", "funeral directors",
}

USER_AGENT = (
    "Mozilla/5.0 (compatible; CanadaFuneralIntelligence/1.0; "
    "+public-business-verification)"
)

_thread_local = threading.local()


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def normalize(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.casefold()
    value = value.replace("\\.", ".")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def tokens(value):
    return set(normalize(value).split())


def company_tokens(company):
    all_tokens = tokens(company)
    core = {
        token for token in all_tokens
        if token not in GENERIC_TOKENS and len(token) >= 2
    }
    return core or {
        token for token in all_tokens
        if len(token) >= 2
    }


def host_for(url):
    try:
        host = (urlsplit(str(url or "")).hostname or "").casefold().rstrip(".")
    except ValueError:
        return ""

    return host[4:] if host.startswith("www.") else host


def base_domain_url(url):
    try:
        parsed = urlsplit(str(url or ""))
    except ValueError:
        return ""

    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""

    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            "/",
            "",
            "",
        )
    )


def domain_matches(host, domains):
    return any(
        host == item or host.endswith("." + item)
        for item in domains
    )


def overlap_ratio(needed, observed):
    needed = set(needed)
    if not needed:
        return 0.0
    return len(needed & set(observed)) / len(needed)


def phrase_present(company, text):
    company_norm = normalize(company)
    text_norm = normalize(text)

    if not company_norm or not text_norm:
        return False

    return company_norm in text_norm


def offline_candidate_score(row, candidate):
    company = str(row.get("company") or "")
    city = str(row.get("city") or "")
    province = str(row.get("province") or "")

    name = str(candidate.get("name") or "")
    snippet = str(candidate.get("snippet") or "")
    url = str(candidate.get("url") or "")
    host = host_for(url)

    combined = " ".join((name, snippet, host, url))
    observed = tokens(combined)
    core = company_tokens(company)

    overlap = overlap_ratio(core, observed)

    score = 0.0
    reasons = []

    if phrase_present(company, combined):
        score += 42
        reasons.append("exact_company_phrase")

    if overlap:
        points = 38 * overlap
        score += points
        reasons.append(f"company_token_overlap={overlap:.2f}")

    city_norm = normalize(city)
    if city_norm and city_norm in normalize(combined):
        score += 16
        reasons.append("city_match")

    province_norm = normalize(province)
    if province_norm and re.search(
        rf"\b{re.escape(province_norm)}\b",
        normalize(combined),
    ):
        score += 5
        reasons.append("province_match")

    host_tokens = tokens(host)
    host_overlap = overlap_ratio(core, host_tokens)

    if host_overlap >= 0.50:
        score += 14
        reasons.append(f"domain_token_overlap={host_overlap:.2f}")
    elif host_overlap > 0:
        score += 6
        reasons.append(f"domain_token_overlap={host_overlap:.2f}")

    if any(term in normalize(combined) for term in FUNERAL_TERMS):
        score += 6
        reasons.append("funeral_relevance")

    if domain_matches(host, DIRECTORY_DOMAINS):
        score -= 55
        reasons.append("directory_or_aggregator_penalty")

    if domain_matches(host, HOSTED_FIRST_PARTY):
        score += 3
        reasons.append("known_funeral_hosting_platform")

    if candidate.get("_existing_candidate"):
        score += 15
        reasons.append("existing_under_review_candidate")

    rank = candidate.get("rank")
    try:
        rank = int(rank)
    except (TypeError, ValueError):
        rank = 10

    score += max(0, 5 - min(rank, 5))

    return {
        "score": round(score, 2),
        "company_overlap": round(overlap, 4),
        "host_overlap": round(host_overlap, 4),
        "reasons": reasons,
        "host": host,
    }


def get_session():
    session = getattr(_thread_local, "session", None)

    if session is None:
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": (
                    "text/html,application/xhtml+xml,"
                    "application/xml;q=0.9,*/*;q=0.5"
                ),
            }
        )
        _thread_local.session = session

    return session


def bounded_fetch(url, timeout, max_bytes):
    if not public_web_url(url):
        return {
            "ok": False,
            "url": url,
            "error": "initial_url_not_public",
        }

    session = get_session()

    try:
        response = session.get(
            url,
            timeout=(5, timeout),
            allow_redirects=True,
            stream=True,
        )
    except requests.RequestException as exc:
        return {
            "ok": False,
            "url": url,
            "error": f"request_error:{type(exc).__name__}",
        }

    final_url = str(response.url or "")

    if not public_web_url(final_url):
        response.close()
        return {
            "ok": False,
            "url": url,
            "final_url": final_url,
            "error": "redirect_target_not_public",
        }

    if response.status_code >= 400:
        code = response.status_code
        response.close()
        return {
            "ok": False,
            "url": url,
            "final_url": final_url,
            "status_code": code,
            "error": f"http_{code}",
        }

    content_type = str(response.headers.get("Content-Type") or "").casefold()

    if (
        content_type
        and "html" not in content_type
        and "text/" not in content_type
        and "xml" not in content_type
    ):
        response.close()
        return {
            "ok": False,
            "url": url,
            "final_url": final_url,
            "status_code": response.status_code,
            "error": "non_text_content",
        }

    chunks = []
    total = 0

    try:
        for chunk in response.iter_content(chunk_size=16384):
            if not chunk:
                continue

            remaining = max_bytes - total

            if remaining <= 0:
                break

            chunk = chunk[:remaining]
            chunks.append(chunk)
            total += len(chunk)

            if total >= max_bytes:
                break
    finally:
        response.close()

    raw = b"".join(chunks)

    encoding = response.encoding or "utf-8"

    try:
        text = raw.decode(encoding, errors="replace")
    except LookupError:
        text = raw.decode("utf-8", errors="replace")

    return {
        "ok": True,
        "url": url,
        "final_url": final_url,
        "status_code": response.status_code,
        "content_type": content_type,
        "bytes_read": len(raw),
        "html": text,
    }


def visible_text(raw_html):
    try:
        soup = BeautifulSoup(raw_html, "html.parser")

        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()

        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        text = soup.get_text(" ", strip=True)

        return title, html.unescape(text)
    except Exception:
        return "", re.sub(r"<[^>]+>", " ", raw_html)


def verification_score(row, candidate, fetched, offline):
    company = str(row.get("company") or "")
    city = str(row.get("city") or "")
    province = str(row.get("province") or "")

    title, body = visible_text(fetched.get("html") or "")

    candidate_text = " ".join(
        (
            str(candidate.get("name") or ""),
            str(candidate.get("snippet") or ""),
        )
    )

    final_url = str(fetched.get("final_url") or candidate.get("url") or "")
    host = host_for(final_url)

    evidence_text = " ".join(
        (
            title,
            body[:350000],
            candidate_text,
            final_url,
        )
    )

    evidence_norm = normalize(evidence_text)
    evidence_tokens = tokens(evidence_text)
    core = company_tokens(company)

    company_overlap = overlap_ratio(core, evidence_tokens)
    exact_company = phrase_present(company, evidence_text)

    city_norm = normalize(city)
    city_match = bool(city_norm and city_norm in evidence_norm)

    province_norm = normalize(province)
    province_match = bool(
        province_norm
        and re.search(
            rf"\b{re.escape(province_norm)}\b",
            evidence_norm,
        )
    )

    funeral_match = any(
        term in evidence_norm
        for term in FUNERAL_TERMS
    )

    host_overlap = overlap_ratio(core, tokens(host))
    directory = domain_matches(host, DIRECTORY_DOMAINS)
    hosted_platform = domain_matches(host, HOSTED_FIRST_PARTY)

    score = 0.0
    reasons = []

    if exact_company:
        score += 0.42
        reasons.append("exact_company_phrase_on_page")

    score += 0.30 * company_overlap
    reasons.append(f"page_company_overlap={company_overlap:.2f}")

    if city_match:
        score += 0.13
        reasons.append("city_on_page")

    if province_match:
        score += 0.04
        reasons.append("province_on_page")

    if funeral_match:
        score += 0.08
        reasons.append("funeral_relevance_on_page")

    if host_overlap >= 0.50:
        score += 0.07
        reasons.append(f"domain_company_overlap={host_overlap:.2f}")
    elif host_overlap > 0:
        score += 0.03
        reasons.append(f"domain_company_overlap={host_overlap:.2f}")

    if hosted_platform:
        score += 0.02
        reasons.append("recognized_funeral_hosting_platform")

    if candidate.get("_existing_candidate"):
        score += 0.03
        reasons.append("existing_under_review_candidate")

    if directory:
        score -= 0.45
        reasons.append("directory_or_aggregator")

    score = max(0.0, min(score, 1.0))

    strong_identity = (
        exact_company
        or company_overlap >= 0.75
        or (
            company_overlap >= 0.60
            and host_overlap >= 0.50
        )
    )

    geographic_support = (
        city_match
        or province_match
        or host_overlap >= 0.50
        or exact_company
    )

    verified = (
        not directory
        and funeral_match
        and strong_identity
        and geographic_support
        and score >= 0.74
    )

    high = verified and score >= 0.84

    return {
        "verification_score": round(score, 4),
        "verified": verified,
        "high_confidence": high,
        "exact_company": exact_company,
        "company_overlap": round(company_overlap, 4),
        "city_match": city_match,
        "province_match": province_match,
        "funeral_match": funeral_match,
        "host_overlap": round(host_overlap, 4),
        "host": host,
        "title": title[:500],
        "reasons": reasons,
        "offline_score": offline["score"],
    }


def prepare_candidates(row, search_row, top_n):
    candidates = []

    existing = str(
        row.get("candidate_website")
        or search_row.get("existing_candidate_website")
        or ""
    ).strip()

    if existing:
        candidates.append(
            {
                "rank": 0,
                "name": f"Existing candidate for {row.get('company', '')}",
                "url": existing,
                "display_url": existing,
                "snippet": "",
                "_existing_candidate": True,
            }
        )

    for candidate in search_row.get("candidate_results") or []:
        if not isinstance(candidate, dict):
            continue

        url = str(candidate.get("url") or "").strip()

        if not url:
            continue

        copied = dict(candidate)
        copied["_existing_candidate"] = False
        candidates.append(copied)

    scored = []

    for candidate in candidates:
        offline = offline_candidate_score(row, candidate)
        scored.append((offline["score"], candidate, offline))

    scored.sort(
        key=lambda item: (
            item[0],
            -int(item[1].get("rank") or 0),
        ),
        reverse=True,
    )

    selected = []
    seen_hosts = set()

    for _, candidate, offline in scored:
        host = offline["host"]

        if not host or host in seen_hosts:
            continue

        if domain_matches(host, DIRECTORY_DOMAINS):
            continue

        seen_hosts.add(host)

        selected.append(
            {
                "candidate": candidate,
                "offline": offline,
            }
        )

        if len(selected) >= top_n:
            break

    return selected, scored


def verify_record(row, search_row, top_n, timeout, max_bytes):
    record_id = str(row.get("directory_record_id") or "")

    selected, all_scored = prepare_candidates(
        row,
        search_row,
        top_n,
    )

    attempts = []
    verified_matches = []

    for item in selected:
        candidate = item["candidate"]
        offline = item["offline"]

        original_url = str(candidate.get("url") or "")
        fetch_urls = [original_url]

        base = base_domain_url(original_url)

        if base and base != original_url:
            fetch_urls.append(base)

        best_for_candidate = None

        for fetch_url in fetch_urls:
            fetched = bounded_fetch(
                fetch_url,
                timeout,
                max_bytes,
            )

            attempt = {
                "candidate_rank": candidate.get("rank"),
                "candidate_name": candidate.get("name"),
                "candidate_url": original_url,
                "fetch_url": fetch_url,
                "offline_score": offline["score"],
                "offline_reasons": offline["reasons"],
                "fetch_ok": fetched.get("ok", False),
                "final_url": fetched.get("final_url"),
                "status_code": fetched.get("status_code"),
                "error": fetched.get("error"),
            }

            if fetched.get("ok"):
                verified = verification_score(
                    row,
                    candidate,
                    fetched,
                    offline,
                )

                attempt.update(verified)

                if (
                    best_for_candidate is None
                    or verified["verification_score"]
                    > best_for_candidate["verification_score"]
                ):
                    best_for_candidate = attempt

            attempts.append(attempt)

            if attempt.get("verified"):
                break

        if best_for_candidate and best_for_candidate.get("verified"):
            verified_matches.append(best_for_candidate)

    verified_matches.sort(
        key=lambda item: item.get("verification_score", 0),
        reverse=True,
    )

    if verified_matches:
        best = verified_matches[0]

        status = (
            "VERIFIED_HIGH"
            if best.get("high_confidence")
            else "VERIFIED"
        )

        website = (
            best.get("final_url")
            or best.get("candidate_url")
            or ""
        )

        return {
            "directory_record_id": record_id,
            "directory_index": row.get("directory_index"),
            "company": row.get("company", ""),
            "city": row.get("city", ""),
            "province": row.get("province", ""),
            "original_website_status": row.get("website_status", ""),
            "verification_complete": True,
            "status": status,
            "website": website,
            "domain": host_for(website),
            "confidence": (
                "HIGH"
                if status == "VERIFIED_HIGH"
                else "MEDIUM"
            ),
            "verification_score": best.get("verification_score"),
            "evidence": best,
            "attempts": attempts,
        }

    successful = [
        attempt
        for attempt in attempts
        if attempt.get("fetch_ok")
        and attempt.get("verification_score") is not None
    ]

    successful.sort(
        key=lambda item: item.get("verification_score", 0),
        reverse=True,
    )

    if successful and successful[0].get("verification_score", 0) >= 0.52:
        best = successful[0]

        return {
            "directory_record_id": record_id,
            "directory_index": row.get("directory_index"),
            "company": row.get("company", ""),
            "city": row.get("city", ""),
            "province": row.get("province", ""),
            "original_website_status": row.get("website_status", ""),
            "verification_complete": True,
            "status": "REVIEW",
            "website": "",
            "domain": "",
            "confidence": "REVIEW",
            "verification_score": best.get("verification_score"),
            "review_candidate": (
                best.get("final_url")
                or best.get("candidate_url")
            ),
            "evidence": best,
            "attempts": attempts,
        }

    return {
        "directory_record_id": record_id,
        "directory_index": row.get("directory_index"),
        "company": row.get("company", ""),
        "city": row.get("city", ""),
        "province": row.get("province", ""),
        "original_website_status": row.get("website_status", ""),
        "verification_complete": True,
        "status": "UNRESOLVED",
        "website": "",
        "domain": "",
        "confidence": "UNRESOLVED",
        "verification_score": (
            successful[0].get("verification_score")
            if successful
            else 0
        ),
        "attempts": attempts,
        "offline_top_candidates": [
            {
                "score": offline["score"],
                "url": candidate.get("url"),
                "name": candidate.get("name"),
                "reasons": offline["reasons"],
            }
            for _, candidate, offline in all_scored[:5]
        ],
    }


def write_derived(outdir, results, total):
    ordered = sorted(
        results.values(),
        key=lambda row: int(row.get("directory_index") or 0),
    )

    verified = [
        row for row in ordered
        if row.get("status") in {"VERIFIED_HIGH", "VERIFIED"}
    ]

    review = [
        row for row in ordered
        if row.get("status") in {"REVIEW", "UNRESOLVED"}
    ]

    source = [
        {
            "directory_record_id": row["directory_record_id"],
            "company": row["company"],
            "city": row["city"],
            "province": row["province"],
            "website": row["website"],
            "website_status": "selected",
            "record_type": "directory_verified",
            "source": "langsearch_plus_first_party_verification",
            "verification_confidence": row["confidence"],
            "verification_score": row["verification_score"],
        }
        for row in verified
    ]

    status_counts = Counter(
        row.get("status") or ""
        for row in ordered
    )

    unique_domains = {
        row.get("domain")
        for row in verified
        if row.get("domain")
    }

    summary = {
        "input_records": total,
        "completed_records": len(ordered),
        "remaining": total - len(ordered),
        "status_counts": dict(status_counts),
        "verified_records": len(verified),
        "verified_unique_domains": len(unique_domains),
        "review_or_unresolved": len(review),
    }

    atomic_json(outdir / "verified_websites.json", ordered)
    atomic_json(outdir / "verified_source.json", source)
    atomic_json(outdir / "review_queue.json", review)
    atomic_json(outdir / "summary.json", summary)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--search-results", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--top-candidates", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=12)
    parser.add_argument("--max-bytes", type=int, default=600000)
    args = parser.parse_args()

    queue = json.loads(
        args.queue.read_text(encoding="utf-8")
    )

    searches = json.loads(
        args.search_results.read_text(encoding="utf-8")
    )

    if len(queue) != 890:
        raise SystemExit(
            f"STOP: expected 890 queue records, got {len(queue)}"
        )

    search_by_id = {
        str(row.get("directory_record_id")): row
        for row in searches
        if row.get("directory_record_id")
    }

    if len(search_by_id) != 890:
        raise SystemExit(
            f"STOP: expected 890 search records, got {len(search_by_id)}"
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)

    output_file = args.output_dir / "verified_websites.json"

    if output_file.is_file():
        previous = json.loads(
            output_file.read_text(encoding="utf-8")
        )
    else:
        previous = []

    results = {
        str(row.get("directory_record_id")): row
        for row in previous
        if row.get("directory_record_id")
        and row.get("verification_complete")
    }

    pending = [
        row for row in queue
        if str(row.get("directory_record_id")) not in results
    ]

    print("input records:", len(queue))
    print("already completed:", len(results))
    print("pending:", len(pending))
    print("workers:", args.workers)
    print("top candidates per record:", args.top_candidates)
    print(flush=True)

    def work(row):
        record_id = str(row.get("directory_record_id") or "")
        return verify_record(
            row,
            search_by_id[record_id],
            args.top_candidates,
            args.timeout,
            args.max_bytes,
        )

    completed_this_run = 0

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=max(1, args.workers)
    ) as executor:
        futures = {
            executor.submit(work, row): row
            for row in pending
        }

        for future in concurrent.futures.as_completed(futures):
            row = futures[future]
            record_id = str(row.get("directory_record_id") or "")

            try:
                result = future.result()
            except Exception as exc:
                result = {
                    "directory_record_id": record_id,
                    "directory_index": row.get("directory_index"),
                    "company": row.get("company", ""),
                    "city": row.get("city", ""),
                    "province": row.get("province", ""),
                    "verification_complete": False,
                    "status": "ERROR",
                    "error": f"{type(exc).__name__}: {exc}",
                }

            if result.get("verification_complete"):
                results[record_id] = result

            completed_this_run += 1

            print(
                f"[{completed_this_run}/{len(pending)}] "
                f"{record_id} "
                f"{row.get('company', '')} -> "
                f"{result.get('status')}",
                flush=True,
            )

            if result.get("verification_complete"):
                write_derived(
                    args.output_dir,
                    results,
                    len(queue),
                )

    write_derived(
        args.output_dir,
        results,
        len(queue),
    )

    summary = json.loads(
        (args.output_dir / "summary.json").read_text(
            encoding="utf-8"
        )
    )

    print()
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
