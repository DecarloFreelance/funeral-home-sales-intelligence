from __future__ import annotations

import html as html_lib
import re
from datetime import datetime
from typing import Any, Dict, Iterable, Iterator, List
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from enrichment.evidence import fact, reconcile_facts, utc_now
from technology_detector import detect_technology


DETECTOR = "public_business_enrichment"
VERSION = "1.4.1"
SOCIAL_HOSTS = {
    "facebook.com": "facebook",
    "instagram.com": "instagram",
    "linkedin.com": "linkedin",
    "youtube.com": "youtube",
    "x.com": "x",
    "twitter.com": "x",
}
SERVICE_PATTERNS = {
    "services.cremation": r"\bcremation\b",
    "services.burial": r"\b(?:burial|interment)\b",
    "services.preplanning": r"\b(?:pre[ -]?planning|pre[ -]?arrangements?|plan ahead)\b",
    "services.obituaries": r"\bobituar(?:y|ies)\b",
    "services.grief_resources": r"\b(?:grief support|bereavement|aftercare)\b",
    "digital.livestream": r"\b(?:live[ -]?stream|webcast)\b",
    "digital.online_arrangements": r"\b(?:online|virtual) (?:funeral )?arrangements?\b",
    "digital.online_payment": r"\b(?:pay online|online payment|make a payment)\b",
    "digital.flowers": r"\b(?:send|order|shop) flowers?\b",
    "business.accessibility": r"\b(?:wheelchair accessible|accessibility|accessible entrance)\b",
}
ROLE_CATEGORIES = {
    "owner": ("OWNER", 0.95),
    "president": ("EXECUTIVE", 0.9),
    "general manager": ("MANAGER", 0.85),
    "managing director": ("MANAGER", 0.9),
    "funeral director": ("FUNERAL_DIRECTOR", 0.75),
}
PARENT_PATTERNS = (
    r"\b(?:a\s+division\s+of|division\s+of)\s+"
    r"([A-Z][A-Za-z0-9&'’., ()-]{2,100}?(?:Ltd\.?|Limited|Inc\.?|Corporation|Corp\.?|ULC))(?=[.\n]|$)",
    r"\b([A-Z][A-Za-z0-9&'’., ()-]{2,100}?(?:Ltd\.?|Limited|Inc\.?|Corporation|Corp\.?|ULC))"
    r"\s+operating\s+as\b",
)


def _nodes(value: Any) -> Iterator[Dict[str, Any]]:
    if isinstance(value, dict):
        if "@graph" in value:
            yield from _nodes(value["@graph"])
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _nodes(item)


def _values(value: Any) -> List[Any]:
    if value in (None, "", []):
        return []
    return value if isinstance(value, list) else [value]


def _snippet(text: str, match: re.Match[str], radius: int = 90) -> str:
    start = max(0, match.start() - radius)
    end = min(len(text), match.end() + radius)
    return re.sub(r"\s+", " ", text[start:end]).strip()


def enrich_company(
    domain: str,
    pages: Iterable[Dict[str, Any]],
    business_profile: Dict[str, Any] | None = None,
    contacts: Dict[str, Any] | None = None,
    *,
    observed_at=None,
) -> Dict[str, Any]:
    """Extract public B2B facts without performing additional network calls."""
    observed_at = observed_at or utc_now()
    pages = list(pages)
    profile = business_profile or {}
    contacts = contacts or {}
    facts: List[Dict[str, Any]] = []

    def page_observation(page):
        value = (page.get("crawl") or {}).get("observedAt")
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return observed_at

    observation_by_url = {str(page.get("url") or ""): page_observation(page) for page in pages}
    current_observed_at = page_observation(pages[0]) if pages else observed_at

    def add(field, value, source, source_url, source_type, confidence, state, evidence, derived=False, days=180):
        if value not in (None, "", [], {}):
            facts.append(fact(
                domain, field, value, source=source, source_url=source_url,
                source_type=source_type, observed_at=current_observed_at, detector=DETECTOR,
                version=VERSION, confidence=confidence, verification_state=state,
                evidence=evidence, derived=derived, freshness_days=days,
            ))

    provenance = profile.get("provenance") or []
    primary_source_url = next(
        (item.get("source_url", "") for item in provenance if isinstance(item, dict)), ""
    )
    add("organization.canonical_domain", domain, "crawl_queue", primary_source_url,
        "discovery", 0.95, "LOCALLY_VALIDATED", f"Normalized crawl domain: {domain}", days=365)
    add("organization.canonical_name", profile.get("company"), "discovery", primary_source_url,
        "discovery", 0.7, "DISCOVERED", str(profile.get("company", "")))
    first_page_url = str(pages[0].get("url") or "") if pages else ""
    first_parsed = urlsplit(first_page_url)
    if first_parsed.scheme in {"http", "https"} and first_parsed.hostname:
        website = f"{first_parsed.scheme}://{first_parsed.netloc}/"
        add("organization.website", website, "successful_crawl", first_page_url,
            "website", 0.95, "LOCALLY_VALIDATED", f"Successfully crawled: {first_page_url}", days=90)
    for name in profile.get("business_names") or []:
        add("organization.business_name", name, "discovery", primary_source_url,
            "discovery", 0.7, "DISCOVERED", str(name))
    for location in profile.get("locations") or []:
        if isinstance(location, dict):
            source_url = location.get("source_url") or primary_source_url
            address = {key: location.get(key) for key in ("address", "city", "province", "country") if location.get(key)}
            add("organization.location", address, "discovery", source_url, "directory",
                0.72, "DISCOVERED", ", ".join(address.values()), days=120)

    for page in pages:
        current_observed_at = page_observation(page)
        page_url = str(page.get("url") or "")
        text = str(page.get("text") or page.get("markdown") or "")
        metadata = page.get("metadata") or {}
        canonical = metadata.get("canonicalUrl")
        if canonical:
            canonical = urljoin(page_url, str(canonical))
            if (urlsplit(canonical).hostname or "").lower().removeprefix("www.") == domain.removeprefix("www."):
                add("website.canonical_page", canonical, "html_metadata", page_url, "website",
                    0.9, "LOCALLY_VALIDATED", f"Canonical link: {canonical}", days=90)

        json_values = metadata.get("jsonLd") or []
        for node in _nodes(json_values):
            types = {str(item).lower() for item in _values(node.get("@type"))}
            if not types.intersection({"organization", "localbusiness", "funeralhome", "corporation"}):
                continue
            mappings = {
                "name": "organization.business_name",
                "legalName": "organization.legal_name",
                "alternateName": "organization.business_name",
                "foundingDate": "organization.founding_year",
                "parentOrganization": "organization.parent_organization",
            }
            for source_field, target_field in mappings.items():
                for value in _values(node.get(source_field)):
                    if isinstance(value, dict):
                        value = value.get("name") or value.get("@id")
                    if isinstance(value, str) and source_field in {"name", "legalName", "alternateName"}:
                        value = re.sub(r"\s+", " ", html_lib.unescape(value)).strip()
                    add(target_field, value, "schema.org", page_url, "structured_data",
                        0.82, "EXTRACTED", f"JSON-LD {source_field}: {value}")
            for same_as in _values(node.get("sameAs")):
                social_host = (urlsplit(str(same_as)).hostname or "").lower().removeprefix("www.")
                if any(social_host == host or social_host.endswith("." + host) for host in SOCIAL_HOSTS):
                    add("organization.social_profile", same_as, "schema.org", page_url,
                        "structured_data", 0.8, "EXTRACTED", f"JSON-LD sameAs: {same_as}", days=90)

        html = str(page.get("html") or "")
        if html:
            soup = BeautifulSoup(html, "html.parser")
            for anchor in soup.find_all("a", href=True):
                href = urljoin(page_url, anchor.get("href", ""))
                host = (urlsplit(href).hostname or "").lower().removeprefix("www.")
                platform = next((label for social_host, label in SOCIAL_HOSTS.items()
                                 if host == social_host or host.endswith("." + social_host)), None)
                if platform:
                    add("organization.social_profile", href, "html_link", page_url, "website",
                        0.75, "EXTRACTED", f"Public {platform} link: {href}", days=90)
                label = anchor.get_text(" ", strip=True).lower()
                path = urlsplit(href).path.lower()
                if re.search(r"\b(?:careers?|jobs?|employment|join our team)\b", f"{label} {path}"):
                    add("business.careers_page", href, "html_link", page_url, "website",
                        0.8, "EXTRACTED", f"Careers link: {href}", days=45)
            for technology, detection in detect_technology(html).items():
                add("technology.platform", technology, "html_signature", page_url,
                    "website", detection["confidence"], "EXTRACTED",
                    f"Public HTML signature: {detection['marker']}", days=90)

        for field, pattern in SERVICE_PATTERNS.items():
            match = re.search(pattern, text, re.I)
            if match:
                add(field, True, "page_text", page_url, "website", 0.78,
                    "EXTRACTED", _snippet(text, match), days=90)
        for pattern in PARENT_PATTERNS:
            match = re.search(pattern, text, re.I)
            if match:
                parent = re.sub(r"\s+", " ", match.group(1)).strip(" ,.")
                add("organization.parent_organization", parent, "page_text", page_url,
                    "website", 0.9, "EXTRACTED", _snippet(text, match), days=120)

    for person in contacts.get("people") or []:
        if not isinstance(person, dict) or not person.get("name"):
            continue
        source_url = str(person.get("source_url") or "")
        current_observed_at = observation_by_url.get(source_url, observed_at)
        title = str(person.get("title") or "")
        add("contact.person", {"name": person["name"], "title": title},
            person.get("source", "contact_extractor"), source_url, "website", 0.76,
            "EXTRACTED", f"{person['name']} — {title}", days=60)
        lowered = title.lower()
        category = next((value for key, value in ROLE_CATEGORIES.items() if key in lowered), None)
        if category:
            role, probability = category
            add("contact.role_category", {"name": person["name"], "role": role,
                "decision_maker_probability": probability}, "role_classifier", source_url,
                "derived", probability, "INFERRED", f"Derived from observed title: {title}",
                derived=True, days=60)

    email_validation = {item.get("email"): item for item in contacts.get("email_validation") or []}
    for item in contacts.get("email_sources") or []:
        value = str(item.get("value") or "").lower()
        validation = email_validation.get(value, {})
        current_observed_at = observation_by_url.get(str(item.get("source_url") or ""), observed_at)
        state = validation.get("verification_state") or "EXTRACTED"
        if state not in {"LOCAL_VALID", "DNS_VALID", "EXTERNALLY_VERIFIED"}:
            state = "EXTRACTED"
        add("contact.public_email", value, item.get("source_type", "contact_extractor"),
            item.get("source_url", ""), item.get("source_type", "website"),
            (validation.get("confidence", 65) or 65) / 100, state,
            f"Public business email observed: {value}", days=60)
    phone_validation = {item.get("phone"): item for item in contacts.get("phone_verification") or []}
    for item in contacts.get("phone_sources") or []:
        value = str(item.get("value") or "")
        validation = phone_validation.get(value, {})
        current_observed_at = observation_by_url.get(str(item.get("source_url") or ""), observed_at)
        state = validation.get("verification_state") or "EXTRACTED"
        if state not in {"METADATA_VALIDATED", "LOCALLY_VALIDATED", "EXTERNALLY_VERIFIED"}:
            state = "EXTRACTED"
        add("contact.public_phone", validation.get("normalized") or value,
            item.get("source_type", "contact_extractor"), item.get("source_url", ""),
            item.get("source_type", "website"), (validation.get("confidence", 65) or 65) / 100,
            state, f"Public business phone observed: {value}", days=60)

    for address in contacts.get("addresses") or []:
        if isinstance(address, dict):
            current_observed_at = observation_by_url.get(str(address.get("source_url") or ""), observed_at)
            value = {key: item for key, item in address.items() if key not in {"source_url", "formatted"}}
            add("organization.location", value or address.get("formatted"), "contact_extractor",
                address.get("source_url", ""), "structured_data", 0.8, "EXTRACTED",
                address.get("formatted", str(value)), days=120)

    reconciled = reconcile_facts(facts)
    return {
        "schema_version": 1,
        "entity_id": domain,
        "generated_at": observed_at.isoformat(),
        "detector": DETECTOR,
        "detector_version": VERSION,
        "facts": reconciled,
        "conflicted_fields": sorted({item["field"] for item in reconciled if item["verification_state"] == "CONFLICTED"}),
        "fact_count": len(reconciled),
    }
