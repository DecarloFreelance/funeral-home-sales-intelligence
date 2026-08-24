from __future__ import annotations

from datetime import datetime, timezone
import re
import unicodedata
from typing import Any, Dict, Iterable, List
from urllib.parse import urlsplit

from automation.agents import RecordAgent


VERSION = "1.0.3"
IDENTITY_CODES = {
    "NO_USABLE_WEBSITE_EVIDENCE",
    "POSSIBLE_DUPLICATE_ORGANIZATION",
    "EMAIL_DOMAIN_MISMATCH",
    "MULTI_LOCATION_ACCOUNT_REVIEW",
    "SHARED_ADDRESS_REVIEW",
    "ORGANIZATION_WEBSITE_MISMATCH",
    "EMAIL_DOMAIN_FIRST_PARTY_CONFIRMED",
}
QUESTIONS = {
    "NO_USABLE_WEBSITE_EVIDENCE": "Does this organization have a current official website or evidenced parent-network location page?",
    "POSSIBLE_DUPLICATE_ORGANIZATION": "Are these duplicate records, related locations, a rebrand, or distinct organizations?",
    "EMAIL_DOMAIN_MISMATCH": "Is this email first-party, parent-domain, third-party, directory-only, incorrectly attributed, or unknown?",
    "MULTI_LOCATION_ACCOUNT_REVIEW": "Is CRM identity network-level or location-level, and which contacts apply at each scope?",
    "SHARED_ADDRESS_REVIEW": "Does this address represent duplication, related brands, co-location, transition, or distinct organizations?",
    "ORGANIZATION_WEBSITE_MISMATCH": "Is the supplied website stale, reassigned, a parent page, or mapped to the wrong organization?",
    "EMAIL_DOMAIN_FIRST_PARTY_CONFIRMED": "Was this cross-domain email directly published by the organization's first-party website?",
}
STOP_WORDS = {
    "and", "the", "inc", "ltd", "limited", "services", "service", "funeral",
    "home", "homes", "chapel", "centre", "center", "cremation", "crematorium",
    "cemetery", "memorial",
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _tokens(value: Any) -> set[str]:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().casefold()
    return {
        token for token in re.findall(r"[a-z0-9]+", text)
        if len(token) > 2 and token not in STOP_WORDS
    }


def _host(value: Any) -> str:
    return (urlsplit(str(value or "")).hostname or "").lower().removeprefix("www.")


def _homepage_redirect(item: Dict[str, Any]) -> Dict[str, Any] | None:
    entity = str(item.get("domain") or "").lower().removeprefix("www.")
    for attempt in item.get("attempts") or []:
        if attempt.get("outcome") != "CROSS_DOMAIN_REDIRECT":
            continue
        attempted = str(attempt.get("url") or "")
        target = str(attempt.get("final_url") or "")
        parsed = urlsplit(attempted)
        if _host(attempted) != entity or parsed.path.rstrip("/"):
            continue
        if target and _host(target) and _host(target) != entity:
            return attempt
    return None


def _location_redirect_resolution(item: Dict[str, Any]) -> Dict[str, Any] | None:
    attempt = _homepage_redirect(item)
    if not attempt:
        return None
    target = str(attempt["final_url"])
    company_tokens = _tokens(item.get("company"))
    target_tokens = _tokens(urlsplit(target).path)
    matched = sorted(company_tokens & target_tokens)
    locations = [value for value in item.get("locations") or [] if isinstance(value, dict)]
    city_tokens = set().union(*(_tokens(value.get("city")) for value in locations)) if locations else set()
    city_match = bool(city_tokens & target_tokens)
    name_ratio = len(matched) / len(company_tokens) if company_tokens else 0.0
    path_segments = [value for value in urlsplit(target).path.rstrip("/").split("/") if value]
    location_identifier = bool(path_segments and path_segments[-1].isdigit())
    named_branch_file = (
        _host(target) == "arbormemorial.ca"
        and bool(path_segments)
        and path_segments[-1].endswith(".html")
        and name_ratio == 1.0
    )

    # A direct redirect from the supplied business domain is strong control evidence,
    # but identity still requires a matching business name and either its location or
    # more than one distinctive name token. Generic brand words never qualify.
    # A numeric network ID distinguishes a page, not the branch represented by
    # that page. Require either matching geography or at least two distinctive
    # business-name tokens before accepting a numbered location URL. This
    # prevents sibling locations with similar names from borrowing one another's
    # network page (observed for Radville and Weyburn Fletcher locations).
    numbered_named_location = location_identifier and len(matched) >= 2
    if not matched or not (city_match or numbered_named_location or named_branch_file):
        return None
    source_urls = sorted({
        str(value.get("source_url") or "") for value in locations if value.get("source_url")
    })
    return {
        "outcome": "LOCATION_PAGE_CONFIRMED",
        "verification_state": "CORROBORATED",
        "confidence": 0.95,
        "identity_critical": True,
        "resolved": True,
        "official_website": target,
        "website_scope": "LOCATION",
        "parent_domain": _host(target),
        "contact_scope": "UNKNOWN",
        "evidence": {
            "redirect_from": attempt.get("url"),
            "redirect_to": target,
            "matched_name_tokens": matched,
            "matched_city_tokens": sorted(city_tokens & target_tokens),
            "association_sources": source_urls,
        },
        "reason": "The supplied business domain directly redirects to a public network location URL matching the listed business identity.",
    }


class ResearchResolutionAgent(RecordAgent):
    """Answer explicit ambiguity questions from bounded, already-collected evidence."""

    name = "research_resolution"
    version = VERSION
    max_attempts = 2

    def fingerprint_payload(self, context):
        item = context.get("research_item") or {}
        return {
            "domain": context.get("domain"),
            "company": item.get("company"),
            "locations": item.get("locations", []),
            "attempts": item.get("attempts", []),
            "findings": context.get("findings", []),
        }

    def run(self, context):
        item = context.get("research_item") or {}
        findings = [value for value in context.get("findings") or [] if value.get("code") in IDENTITY_CODES]
        questions: List[Dict[str, Any]] = []
        location_resolution = _location_redirect_resolution(item)
        for finding in findings:
            code = finding.get("code")
            resolution = location_resolution if code == "NO_USABLE_WEBSITE_EVIDENCE" else None
            if code == "EMAIL_DOMAIN_FIRST_PARTY_CONFIRMED":
                resolution = {
                    "outcome": "FIRST_PARTY_ORGANIZATION_DOMAIN",
                    "verification_state": "DIRECTLY_OBSERVED",
                    "confidence": 0.9,
                    "identity_critical": False,
                    "resolved": True,
                    "evidence": finding.get("evidence"),
                    "reason": "The quality finding records direct publication on the organization's fetched first-party page.",
                }
            questions.append({
                "finding_id": finding.get("id"),
                "finding_code": code,
                "question": QUESTIONS[code],
                "current_evidence": finding.get("evidence"),
                "candidate_sources": [
                    "first_party_redirect", "first_party_parent_or_location_page",
                    "association_directory", "structured_metadata",
                ],
                "outcome": resolution or {
                    "outcome": "REQUIRES_REVIEW",
                    "verification_state": "UNRESOLVED",
                    "confidence": 0.0,
                    "identity_critical": code != "EMAIL_DOMAIN_MISMATCH",
                    "resolved": False,
                    "reason": "The retained evidence does not meet the deterministic resolution threshold.",
                },
            })
        return {"research_resolution": {
            "agent": self.name,
            "agent_version": self.version,
            "entity": context.get("domain"),
            "observed_at": _now(),
            "questions": questions,
            "question_count": len(questions),
            "resolved_count": sum(bool(value["outcome"].get("resolved")) for value in questions),
        }}


def build_resolution_queue(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Create branch-preserving crawl work only for high-confidence location pages."""
    queue = []
    for record in records:
        entity = str(record.get("domain") or "").lower().removeprefix("www.")
        for question in (record.get("research_resolution") or {}).get("questions") or []:
            outcome = question.get("outcome") or {}
            if not outcome.get("resolved") or outcome.get("confidence", 0) < 0.9:
                continue
            website = str(outcome.get("official_website") or "")
            target_domain = _host(website)
            if outcome.get("outcome") != "LOCATION_PAGE_CONFIRMED" or not website or not target_domain:
                continue
            queue.append({
                "company": record.get("company", ""),
                "domain": entity,
                "website": website,
                "url": website,
                "locations": record.get("locations", []),
                "sources": record.get("sources", []),
                "provenance": record.get("provenance", []),
                # Parent-network contact pages have network scope and must not be
                # attributed to this location. The confirmed location page is
                # the only automatically authorized crawl target.
                "priority_urls": [website],
                "resolution": outcome,
                "status": "RESEARCH_RESOLVED_RETRY",
            })
    return sorted(queue, key=lambda value: value["domain"])
