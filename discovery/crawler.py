import json
import time
from collections import deque
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

from discovery.network_safety import public_web_url, resolve_addresses


PRIORITY_LINK_TERMS = (
    "contact",
    "about",
    "team",
    "staff",
    "director",
    "people",
    "location",
)
DEFAULT_USER_AGENT = "FuneralHomeSalesIntelligence/1.0 (+contact-research)"


def _canonical_page_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return ""
    host = parsed.hostname.lower().rstrip(".")
    try:
        port = f":{parsed.port}" if parsed.port else ""
    except ValueError:
        return ""
    path = parsed.path or "/"
    return urlunsplit((parsed.scheme.lower(), host + port, path, parsed.query, ""))


def _same_domain(url: str, domain: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    domain = domain.lower()
    return host == domain or host == f"www.{domain}"


def _site_label(value: str) -> str:
    host = (urlsplit(value).hostname or value).lower().removeprefix("www.")
    parts = host.split(".")
    return parts[-2] if len(parts) >= 2 else host


def _same_brand_redirect(url: str, domain: str) -> bool:
    return bool(_site_label(url)) and _site_label(url) == _site_label(domain)


def _json_ld(soup: BeautifulSoup) -> List[Any]:
    values = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            values.append(json.loads(script.get_text()))
        except (TypeError, json.JSONDecodeError):
            continue
    return values


def _metadata(soup: BeautifulSoup) -> Dict[str, Any]:
    title = soup.title.get_text(" ", strip=True) if soup.title else None
    description_tag = soup.find("meta", attrs={"name": "description"})
    canonical_tag = soup.find("link", rel=lambda value: value and "canonical" in value)
    return {
        "canonicalUrl": canonical_tag.get("href") if canonical_tag else None,
        "title": title,
        "description": description_tag.get("content") if description_tag else None,
        "jsonLd": _json_ld(soup) or None,
    }


def _priority_links(soup: BeautifulSoup, base_url: str, domain: str) -> List[str]:
    links = []
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "")
        label = anchor.get_text(" ", strip=True)
        candidate = _canonical_page_url(urljoin(base_url, href))
        searchable = f"{urlsplit(candidate).path} {label}".lower()
        if (
            candidate
            and _same_domain(candidate, domain)
            and any(term in searchable for term in PRIORITY_LINK_TERMS)
        ):
            links.append(candidate)
    return list(dict.fromkeys(links))


class PriorityPageCrawler:

    def __init__(
        self,
        session=None,
        timeout=15,
        max_pages_per_lead=12,
        max_attempts_per_lead=12,
        delay=0,
        host_resolver=resolve_addresses,
    ):
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_pages_per_lead = max_pages_per_lead
        self.max_attempts_per_lead = max_attempts_per_lead
        self.delay = delay
        self.host_resolver = host_resolver
        self._host_safety = {}
        self.last_report = {}
        self.last_lead_report = {}
        self.session.headers.update({"User-Agent": DEFAULT_USER_AGENT})

    def _public_target(self, url):
        host = (urlsplit(url).hostname or "").lower()
        if host not in self._host_safety:
            self._host_safety[host] = public_web_url(url, self.host_resolver)
        return self._host_safety[host]

    def _get_public(self, url, max_redirects=5):
        """Follow redirects only after authorizing each destination."""
        current = url
        for redirect_count in range(max_redirects + 1):
            if not self._public_target(current):
                return None, current, "UNSAFE_REDIRECT_TARGET"
            response = self.session.get(current, timeout=self.timeout, allow_redirects=False)
            location = response.headers.get("location")
            if response.status_code not in {301, 302, 303, 307, 308} or not location:
                return response, _canonical_page_url(response.url or current), None
            current = _canonical_page_url(urljoin(current, location))
            if not current:
                raise requests.TooManyRedirects("Malformed redirect target")
            if redirect_count == max_redirects:
                raise requests.TooManyRedirects("Redirect limit exceeded")
        raise requests.TooManyRedirects("Redirect limit exceeded")

    def crawl_lead(self, lead: Dict[str, Any]) -> List[Dict[str, Any]]:
        started = time.monotonic()
        domain = str(lead.get("domain", "")).lower().strip()
        homepage = _canonical_page_url(lead.get("url") or lead.get("website") or "")
        resolution = lead.get("resolution") or {}
        resolved_location = (
            resolution.get("outcome") == "LOCATION_PAGE_CONFIRMED"
            and resolution.get("resolved") is True
            and float(resolution.get("confidence", 0)) >= 0.9
            and _canonical_page_url(resolution.get("official_website", "")) == homepage
        )
        website_domain = (urlsplit(homepage).hostname or "").lower().removeprefix("www.")
        outcome = {
            "domain": domain,
            "status": "FAILED",
            "attempts": [],
            "pages": 0,
        }
        if not domain or not homepage or (not _same_domain(homepage, domain) and not resolved_location):
            outcome["reason"] = "INVALID_QUEUE_RECORD"
            self.last_lead_report = outcome
            return []

        seeds = [homepage, *(lead.get("priority_urls") or [])]
        pending = deque(
            url for url in dict.fromkeys(_canonical_page_url(seed) for seed in seeds)
            if url and _same_domain(url, website_domain if resolved_location else domain)
        )
        visited = set()
        records = []
        active_domain = website_domain if resolved_location else domain
        attempts = 0

        while (
            pending
            and len(records) < self.max_pages_per_lead
            and attempts < self.max_attempts_per_lead
        ):
            url = pending.popleft()
            if url in visited:
                continue
            visited.add(url)
            attempts += 1

            if not self._public_target(url):
                outcome["attempts"].append({
                    "url": url,
                    "outcome": "UNSAFE_TARGET",
                    "detail": "Target is not a resolvable public network address",
                })
                continue

            if self.delay and visited != {url}:
                time.sleep(self.delay)

            try:
                response, final_url, safety_error = self._get_public(url)
                if safety_error:
                    outcome["attempts"].append({
                        "url": url,
                        "outcome": safety_error,
                        "final_url": final_url,
                    })
                    continue
                response.raise_for_status()
            except requests.RequestException as error:
                status_code = getattr(getattr(error, "response", None), "status_code", None)
                outcome["attempts"].append({
                    "url": url,
                    "outcome": "HTTP_ERROR" if status_code else "REQUEST_ERROR",
                    "status_code": status_code,
                    "detail": type(error).__name__,
                })
                continue

            final_url = _canonical_page_url(final_url)
            if not self._public_target(final_url):
                outcome["attempts"].append({
                    "url": url,
                    "outcome": "UNSAFE_REDIRECT_TARGET",
                    "final_url": final_url,
                })
                continue
            content_type = response.headers.get("content-type", "")
            if (
                url == homepage
                and not _same_domain(final_url, active_domain)
                and _same_brand_redirect(final_url, active_domain)
            ):
                active_domain = urlsplit(final_url).hostname or active_domain

            if not _same_domain(final_url, active_domain):
                outcome["attempts"].append({
                    "url": url,
                    "outcome": "CROSS_DOMAIN_REDIRECT",
                    "final_url": final_url,
                })
                continue
            if "html" not in content_type.lower():
                outcome["attempts"].append({
                    "url": url,
                    "outcome": "NON_HTML",
                    "status_code": response.status_code,
                    "content_type": content_type,
                })
                continue

            outcome["attempts"].append({
                "url": url,
                "outcome": "SUCCESS",
                "status_code": response.status_code,
                "final_url": final_url,
            })

            soup = BeautifulSoup(response.text, "html.parser")
            for element in soup(["script", "style", "noscript"]):
                element.decompose()
            text = soup.get_text("\n", strip=True)

            records.append({
                "url": final_url,
                "crawl": {
                    "loadedUrl": final_url,
                    "httpStatusCode": response.status_code,
                    "depth": 0 if url == homepage else 1,
                    "contentType": content_type,
                    "observedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                },
                "metadata": _metadata(BeautifulSoup(response.text, "html.parser")),
                "text": text,
                "html": response.text,
                "markdown": text,
                "discovery": {
                    "company": lead.get("company", ""),
                    "business_names": lead.get("business_names", []),
                    "source": lead.get("source", ""),
                    "sources": lead.get("sources", []),
                    "provenance": lead.get("provenance", []),
                    "city": lead.get("city", ""),
                    "province": lead.get("province", ""),
                    "queue_domain": domain,
                    "previous_domain": lead.get("previous_domain", ""),
                    "resolution": lead.get("resolution", {}),
                    "country": lead.get("country", ""),
                    "address": lead.get("address", ""),
                    "phone": lead.get("phone", ""),
                    "email": lead.get("email", ""),
                    "locations": lead.get("locations", []),
                    "record_type": lead.get("record_type", "campaign_lead"),
                    "candidate_type": lead.get("candidate_type", ""),
                    "offers": lead.get("offers", []),
                    "downstream_markets": lead.get("downstream_markets", []),
                    "recommended_motion": lead.get("recommended_motion", ""),
                    "evidence": lead.get("evidence", ""),
                    "evidence_url": lead.get("evidence_url", ""),
                },
            })

            # A confirmed network location URL is scoped to one branch. Generic
            # parent-domain contact/about pages can contain corporate contacts
            # and must not be published as location evidence automatically.
            if not resolved_location:
                for discovered in _priority_links(soup, final_url, active_domain):
                    if discovered not in visited:
                        pending.append(discovered)

        outcome["pages"] = len(records)
        outcome["duration_ms"] = round((time.monotonic() - started) * 1000)
        outcome["status"] = "SUCCESS" if records else "FAILED"
        if not records and "reason" not in outcome:
            outcomes = [attempt["outcome"] for attempt in outcome["attempts"]]
            outcome["reason"] = outcomes[0] if len(set(outcomes)) == 1 and outcomes else "NO_USABLE_PAGES"
        self.last_lead_report = outcome
        return records

    def crawl_queue(
        self,
        leads: Iterable[Dict[str, Any]],
        on_lead=None,
        checkpoint=None,
    ) -> List[Dict[str, Any]]:
        leads = list(leads)
        records = []
        successful_domains = []
        failed_domains = []
        lead_reports = []
        for index, lead in enumerate(leads, start=1):
            lead_records = self.crawl_lead(lead)
            lead_reports.append(self.last_lead_report)
            records.extend(lead_records)
            domain = lead.get("domain", "")
            if lead_records:
                successful_domains.append(domain)
            else:
                failed_domains.append(domain)
            if checkpoint:
                checkpoint(lead_records, self.last_lead_report)
            if on_lead:
                on_lead(index, len(leads), domain, len(lead_records))
        attempt_outcomes = Counter(
            attempt.get("outcome")
            for report in lead_reports for attempt in report.get("attempts", [])
        )
        durations = sorted(report.get("duration_ms", 0) for report in lead_reports)
        self.last_report = {
            "queued_domains": len(leads),
            "successful_domains": len(successful_domains),
            "failed_domains": failed_domains,
            "pages": len(records),
            "leads": lead_reports,
            "attempt_outcomes": dict(sorted(attempt_outcomes.items())),
            "duration_ms": sum(durations),
            "average_domain_duration_ms": round(sum(durations) / len(durations)) if durations else 0,
            "median_domain_duration_ms": durations[len(durations) // 2] if durations else 0,
        }
        return records
