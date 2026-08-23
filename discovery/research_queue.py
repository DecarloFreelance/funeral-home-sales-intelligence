from typing import Any, Dict, Iterable, List

from discovery.crawler import _site_label


def _recommended_action(reason: str) -> str:
    actions = {
        "HTTP_ERROR": "Verify the current website manually or through a search source",
        "REQUEST_ERROR": "Check DNS, TLS, and website availability",
        "CROSS_DOMAIN_REDIRECT": "Review and approve the destination domain",
        "NON_HTML": "Find the business homepage through an alternate source",
        "INVALID_QUEUE_RECORD": "Correct or replace the source website",
    }
    return actions.get(
        reason,
        "Resolve the current website through association, maps, or search research",
    )


def build_research_queue(
    queue: Iterable[Dict[str, Any]],
    pages: Iterable[Dict[str, Any]],
    report: Dict[str, Any] = None,
) -> List[Dict[str, Any]]:
    report_by_domain = {
        lead.get("domain"): lead
        for lead in (report or {}).get("leads", [])
        if lead.get("domain")
    }
    successful_domains = {
        page.get("discovery", {}).get("queue_domain")
        for page in pages
        if page.get("discovery", {}).get("queue_domain")
    }
    successful_labels = {
        _site_label(page.get("url", ""))
        for page in pages
        if page.get("url")
    }

    unresolved = []
    for lead in queue:
        domain = lead.get("domain", "")
        outcome = report_by_domain.get(domain, {})
        succeeded = (
            outcome.get("status") == "SUCCESS"
            or domain in successful_domains
            or _site_label(domain) in successful_labels
        )
        if succeeded:
            continue

        reason = outcome.get("reason") or "HISTORICAL_NO_USABLE_PAGES"
        unresolved.append({
            "domain": domain,
            "company": lead.get("company", ""),
            "website": lead.get("website", lead.get("url", "")),
            "locations": lead.get("locations", []),
            "sources": lead.get("sources", []),
            "provenance": lead.get("provenance", []),
            "status": "RESEARCH_REQUIRED",
            "failure_reason": reason,
            "attempts": outcome.get("attempts", []),
            "recommended_action": _recommended_action(reason),
        })

    return sorted(unresolved, key=lambda item: item["domain"])
