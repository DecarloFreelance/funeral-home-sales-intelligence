#!/usr/bin/env python3

import argparse
import json
from collections import defaultdict
from pathlib import Path

from extraction.contact_extractor import extract_contact_intelligence


TYPE_FIT = {
    "educator_consultant": 40,
    "grief_educator": 42,
    "training_provider": 34,
    "funeral_consultancy": 28,
    "specialist_agency": 20,
}
MOTION_FIT = {
    "MANAGED_LICENSE": 25,
    "DATA_PARTNERSHIP": 18,
    "WHITE_LABEL_PARTNERSHIP": 15,
}


def _contact_review(contacts):
    validations = contacts.get("email_validation") or []
    usable_emails = [
        item["email"] for item in validations
        if item["syntax_valid"] and (
            item["domain_match"] or item["free_provider"]
        ) and "non_sales_mailbox" not in item["risks"]
    ]
    issues = []
    for item in validations:
        if "external_domain" in item["risks"]:
            issues.append(f"Email domain mismatch: {item['email']}")
    return usable_emails, issues


def rank_candidates(queue, pages):
    by_domain = defaultdict(list)
    for page in pages:
        discovery = page.get("discovery") or {}
        domain = discovery.get("queue_domain") or ""
        by_domain[domain].append(page)

    ranked = []
    for candidate in queue:
        domain = candidate["domain"]
        site_pages = by_domain[domain]
        contacts = extract_contact_intelligence(site_pages, domain)
        usable_emails, contact_issues = _contact_review(contacts)
        fit_score = TYPE_FIT.get(candidate.get("candidate_type"), 15)
        fit_score += MOTION_FIT.get(candidate.get("recommended_motion"), 10)
        fit_score += min(12, len(candidate.get("offers") or []) * 3)
        fit_score += min(8, len(candidate.get("downstream_markets") or []) * 2)
        fit_score = min(100, round(fit_score / 87 * 100))

        data_confidence = 35
        data_confidence += 30 if site_pages else 0
        data_confidence += 15 if usable_emails else 0
        data_confidence += 10 if contacts["phones"] else 0
        data_confidence += 10 if contacts["people"] else 0
        data_confidence = min(100, data_confidence)
        priority_score = round(fit_score * .7 + data_confidence * .3)
        competitive_overlap = candidate.get("candidate_type") == "specialist_agency"

        if not site_pages:
            outreach_status = "RESEARCH_REQUIRED"
        elif contact_issues and not usable_emails and not contacts["phones"]:
            outreach_status = "CONTACT_REVIEW_REQUIRED"
        elif usable_emails or contacts["phones"]:
            outreach_status = "READY_FOR_PERSON_REVIEW"
        else:
            outreach_status = "DECISION_MAKER_REQUIRED"
        ranked.append({
            "company": candidate.get("company", ""),
            "domain": domain,
            "website": candidate.get("website", ""),
            "record_type": "platform_candidate",
            "candidate_type": candidate.get("candidate_type", ""),
            "recommended_motion": candidate.get("recommended_motion", ""),
            "fit_score": fit_score,
            "data_confidence": data_confidence,
            "priority_score": priority_score,
            "candidate_score": priority_score,
            "verification_status": "SITE_VERIFIED" if site_pages else "EVIDENCE_ONLY",
            "outreach_status": outreach_status,
            "competitive_overlap": competitive_overlap,
            "contact_issues": contact_issues,
            "usable_emails": usable_emails,
            "pages_crawled": len(site_pages),
            "offers": candidate.get("offers", []),
            "downstream_markets": candidate.get("downstream_markets", []),
            "evidence": candidate.get("evidence", ""),
            "evidence_url": candidate.get("evidence_url", ""),
            "contact_intelligence": contacts,
            "next_action": (
                "Identify and confirm the owner before preparing a package-fit message"
                if outreach_status == "READY_FOR_PERSON_REVIEW" else
                "Manually verify current website and decision-maker before outreach"
            ),
        })
    return sorted(ranked, key=lambda item: item["priority_score"], reverse=True)


def main():
    parser = argparse.ArgumentParser(description="Rank verified platform candidates.")
    parser.add_argument("--queue", type=Path, default=Path("data/generated/platform/platform_candidate_queue.json"))
    parser.add_argument("--pages", type=Path, default=Path("data/generated/platform/platform_candidate_crawl.json"))
    parser.add_argument("--output", type=Path, default=Path("data/generated/platform/platform_candidate_results.json"))
    args = parser.parse_args()
    ranked = rank_candidates(
        json.loads(args.queue.read_text(encoding="utf-8")),
        json.loads(args.pages.read_text(encoding="utf-8")),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(ranked, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Ranked {len(ranked)} platform candidates into {args.output}")
    for item in ranked[:10]:
        print(
            f"{item['priority_score']:3}  fit={item['fit_score']:3}  "
            f"confidence={item['data_confidence']:3}  "
            f"{item['recommended_motion']:<24} {item['company']}"
        )


if __name__ == "__main__":
    main()
