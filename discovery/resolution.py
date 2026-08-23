from typing import Any, Dict, Iterable, List, Tuple
from urllib.parse import urlsplit

from discovery.crawler import _canonical_page_url, _site_label
from discovery.ingestion import PRIORITY_PATHS


def _already_covered(website: str, existing_pages: Iterable[Dict[str, Any]]) -> bool:
    target = urlsplit(website)
    target_path = target.path.rstrip("/")
    for page in existing_pages:
        page_url = page.get("url", "")
        parsed = urlsplit(page_url)
        if _site_label(page_url) != _site_label(website):
            continue
        if not target_path:
            return True
        location_prefix = target_path
        segments = target_path.strip("/").split("/")
        if segments[-1] in {"about.html", "obituaries.html"}:
            location_prefix = "/" + "/".join(segments[:-1])
        if parsed.path.startswith(location_prefix):
            return True
    return False


def apply_resolutions(
    research: Iterable[Dict[str, Any]],
    resolutions: Iterable[Dict[str, Any]],
    existing_pages: Iterable[Dict[str, Any]] = (),
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    research_by_domain = {item["domain"]: item for item in research}
    existing_pages = list(existing_pages)
    retry = []
    resolved_existing = []
    applied = set()

    for resolution in resolutions:
        old_domain = resolution.get("old_domain", "")
        item = research_by_domain.get(old_domain)
        website = _canonical_page_url(resolution.get("new_website", ""))
        if not item or not website or resolution.get("confidence") not in {"HIGH", "MEDIUM"}:
            continue

        applied.add(old_domain)
        new_domain = urlsplit(website).hostname or ""
        parsed_website = urlsplit(website)
        origin = f"{parsed_website.scheme}://{parsed_website.netloc}"
        if _already_covered(website, existing_pages):
            resolved_existing.append({
                "old_domain": old_domain,
                "new_domain": new_domain,
                "status": "RESOLVED_EXISTING_CRAWL",
                "evidence_url": resolution.get("evidence_url", ""),
            })
            continue

        retry.append({
            "company": item.get("company", ""),
            "website": website,
            "url": website,
            "domain": new_domain,
            "previous_domain": old_domain,
            "locations": item.get("locations", []),
            "sources": list(dict.fromkeys([*(item.get("sources") or []), "web_resolution"])),
            "source": "web_resolution",
            "provenance": [
                *(item.get("provenance") or []),
                {
                    "source": "web_resolution",
                    "source_url": resolution.get("evidence_url", ""),
                },
            ],
            "priority_urls": [
                f"{origin}{path}" for path in PRIORITY_PATHS
            ],
            "resolution": resolution,
            "status": "PENDING_RETRY",
        })

    unresolved = [
        item for domain, item in research_by_domain.items() if domain not in applied
    ]
    retry_research = []
    for item in retry:
        original = research_by_domain[item["previous_domain"]]
        retry_research.append({
            **original,
            "status": "RESOLUTION_RETRY_REQUIRED",
            "replacement_website": item["website"],
            "resolution": item["resolution"],
            "recommended_action": "Review access restrictions or verify the replacement manually",
        })
    remaining = [*unresolved, *retry_research]
    summary = {
        "research_domains": len(research_by_domain),
        "retry_domains": len(retry),
        "resolved_existing": resolved_existing,
        "unresolved_domains": len(unresolved),
        "unresolved": unresolved,
        "remaining_domains": len(remaining),
        "remaining": sorted(remaining, key=lambda item: item["domain"]),
    }
    return retry, summary
