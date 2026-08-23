import json
import re
from typing import Any, Dict, Iterable, List

from bs4 import BeautifulSoup

from contact_cleaner import clean_contact_data
from intelligence.email_intelligence import validate_emails
from intelligence.phone_intelligence import verify_phones


EMAIL_PATTERN = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
)
PHONE_PATTERN = re.compile(r"(?:\+?1[-.\s]?)?\(?[2-9]\d{2}\)?[-.\s]\d{3}[-.\s]\d{4}")
ROLE_PATTERN = re.compile(
    r"\b(?:licensed\s+)?(?:funeral\s+director|managing\s+director|"
    r"owner|president|general\s+manager)\b",
    re.I,
)
NAME_PATTERN = re.compile(
    r"\b([A-Z][A-Za-z'’-]+(?:\s+[A-Z][A-Za-z'’-]+){1,3})\b"
)
BUSINESS_TYPES = {
    "organization",
    "localbusiness",
    "funeralhome",
    "corporation",
}
NON_NAME_WORDS = {
    "account",
    "alberta",
    "arrangement",
    "arrangements",
    "arranger",
    "arrangers",
    "attendent",
    "attendants",
    "banking",
    "burial",
    "care",
    "caskets",
    "cemeteries",
    "cemetery",
    "certificate",
    "certificates",
    "cost",
    "costs",
    "cremation",
    "crematorium",
    "death",
    "dna",
    "dressing",
    "funeral",
    "hair",
    "honours",
    "important",
    "items",
    "local",
    "making",
    "memorial",
    "notice",
    "operators",
    "original",
    "other",
    "preplanning",
    "read",
    "more",
    "flower",
    "gallery",
    "recognition",
    "service",
    "services",
    "specialist",
    "staff",
    "statements",
    "traditional",
    "transfer",
    "will",
}


def _values(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if item]
    return [str(value).strip()] if str(value).strip() else []


def _json_ld_nodes(value: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(value, dict):
        graph = value.get("@graph")
        if graph is not None:
            yield from _json_ld_nodes(graph)
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _json_ld_nodes(item)


def _parse_html_json_ld(html: str) -> List[Any]:
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    values = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            values.append(json.loads(script.get_text()))
        except (TypeError, json.JSONDecodeError):
            continue
    return values


def _format_address(address: Any) -> Dict[str, str]:
    if isinstance(address, str):
        return {"formatted": address.strip()} if address.strip() else {}
    if not isinstance(address, dict):
        return {}

    result = {
        "street": str(address.get("streetAddress", "")).strip(),
        "city": str(address.get("addressLocality", "")).strip(),
        "province": str(address.get("addressRegion", "")).strip(),
        "postal_code": str(address.get("postalCode", "")).strip(),
        "country": str(address.get("addressCountry", "")).strip(),
    }
    result = {key: value for key, value in result.items() if value}
    if result:
        result["formatted"] = ", ".join(result.values())
    return result


def _clean_line(line: str) -> str:
    return re.sub(r"[#*_`\[\]()]", " ", line).strip(" \t:|-–—")


def _looks_like_person_name(value: str) -> bool:
    match = NAME_PATTERN.fullmatch(value)
    if not match:
        return False
    if any(len(word) > 20 for word in value.split()):
        return False
    lowered = value.lower()
    if "average" in lowered or "excellent" in lowered:
        return False
    words = {word.lower().strip("'’- ") for word in value.split()}
    return not words.intersection(NON_NAME_WORDS)


def _people_from_text(text: str, source_url: str) -> List[Dict[str, str]]:
    lines = [_clean_line(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    people = []

    for index, line in enumerate(lines):
        role_match = ROLE_PATTERN.search(line)
        if not role_match:
            continue

        candidates = [line]
        if index:
            candidates.append(lines[index - 1])
        if index + 1 < len(lines):
            candidates.append(lines[index + 1])

        for candidate in candidates:
            without_role = ROLE_PATTERN.sub("", candidate).strip(" ,:|-–—")
            if _looks_like_person_name(without_role):
                people.append({
                    "name": without_role,
                    "title": role_match.group(0).title(),
                    "source_url": source_url,
                    "source": "page_text",
                })
                break

    return people


def extract_contact_intelligence(
    pages: Iterable[Dict[str, Any]],
    domain: str = "",
    email_provider=None,
    phone_provider=None,
    check_email_dns: bool = False,
) -> Dict[str, Any]:
    pages = list(pages)
    emails: List[str] = []
    phones: List[str] = []
    people: List[Dict[str, str]] = []
    addresses: List[Dict[str, str]] = []
    business_names: List[str] = []
    directory_contacts: List[Dict[str, str]] = []

    for page in pages:
        text = page.get("text") or page.get("markdown") or ""
        source_url = page.get("url", "")
        emails.extend(EMAIL_PATTERN.findall(text))
        phones.extend(PHONE_PATTERN.findall(text))
        people.extend(_people_from_text(text, source_url))

        discovery = page.get("discovery") or {}
        emails.extend(_values(discovery.get("email")))
        phones.extend(_values(discovery.get("phone")))
        business_names.extend(_values(discovery.get("company")))
        business_names.extend(_values(discovery.get("business_names")))
        if discovery.get("contact_name"):
            directory_contacts.append({
                "name": str(discovery["contact_name"]).strip(),
                "title": str(discovery.get("contact_title") or "Directory contact").strip(),
                "source_url": str(discovery.get("source_url") or source_url),
                "source": "directory",
            })
        for location in discovery.get("locations") or []:
            if not isinstance(location, dict):
                continue
            emails.extend(_values(location.get("email")))
            phones.extend(_values(location.get("phone")))
            business_names.extend(_values(location.get("company")))
            if location.get("contact_name"):
                directory_contacts.append({
                    "name": str(location["contact_name"]).strip(),
                    "title": str(location.get("contact_title") or "Directory contact").strip(),
                    "source_url": str(location.get("source_url") or source_url),
                    "source": "directory",
                })
            address = {
                "street": str(location.get("address", "")).strip(),
                "city": str(location.get("city", "")).strip(),
                "province": str(location.get("province", "")).strip(),
                "country": str(location.get("country", "")).strip(),
            }
            address = {key: value for key, value in address.items() if value}
            if address:
                address["formatted"] = ", ".join(address.values())
                address["source_url"] = str(location.get("source_url") or source_url)
                addresses.append(address)

        metadata = page.get("metadata") or {}
        json_ld_values = metadata.get("jsonLd") or []
        json_ld_values = [json_ld_values, *_parse_html_json_ld(page.get("html") or "")]

        for node in _json_ld_nodes(json_ld_values):
            node_types = node.get("@type", [])
            if isinstance(node_types, str):
                node_types = [node_types]
            normalized_types = {str(item).lower() for item in node_types}

            emails.extend(_values(node.get("email")))
            phones.extend(_values(node.get("telephone")))

            if normalized_types & BUSINESS_TYPES:
                business_names.extend(_values(node.get("name")))
                address = _format_address(node.get("address"))
                if address:
                    address["source_url"] = source_url
                    addresses.append(address)

            if "person" in normalized_types and node.get("name"):
                title = str(node.get("jobTitle", "")).strip()
                if ROLE_PATTERN.search(title):
                    people.append({
                        "name": str(node["name"]).strip(),
                        "title": title,
                        "source_url": source_url,
                        "source": "schema.org",
                    })

    cleaned = clean_contact_data(emails, phones, domain)
    email_validation = validate_emails(
        cleaned["emails"], domain, email_provider, check_dns=check_email_dns,
    )
    phone_verification = verify_phones(cleaned["phones"], phone_provider)
    unique_people = list({
        (person["name"].lower(), person["title"].lower()): person
        for person in people
    }.values())
    unique_addresses = list({
        address.get("formatted", "").lower(): address
        for address in addresses
        if address.get("formatted")
    }.values())
    unique_names = list(dict.fromkeys(name for name in business_names if name))
    unique_directory_contacts = list({
        (item["name"].lower(), item["title"].lower(), item["source_url"]): item
        for item in directory_contacts if item["name"]
    }.values())

    # Retain public source attribution separately from normalized/ranked values.
    email_sources = []
    phone_sources = []
    for page in pages:
        text = page.get("text") or page.get("markdown") or ""
        page_url = str(page.get("url") or "")
        discovery = page.get("discovery") or {}
        for value in EMAIL_PATTERN.findall(text):
            email_sources.append({"value": value.lower(), "source_url": page_url, "source_type": "page_text"})
        for value in PHONE_PATTERN.findall(text):
            phone_sources.append({"value": value, "source_url": page_url, "source_type": "page_text"})
        discovery_url = str(discovery.get("source_url") or page_url)
        for value in _values(discovery.get("email")):
            email_sources.append({"value": value.lower(), "source_url": discovery_url, "source_type": "discovery"})
        for value in _values(discovery.get("phone")):
            phone_sources.append({"value": value, "source_url": discovery_url, "source_type": "discovery"})
        for location in discovery.get("locations") or []:
            if not isinstance(location, dict):
                continue
            location_url = str(location.get("source_url") or discovery_url)
            for value in _values(location.get("email")):
                email_sources.append({"value": value.lower(), "source_url": location_url, "source_type": "directory"})
            for value in _values(location.get("phone")):
                phone_sources.append({"value": value, "source_url": location_url, "source_type": "directory"})
        metadata = page.get("metadata") or {}
        json_ld_values = [metadata.get("jsonLd") or [], *_parse_html_json_ld(page.get("html") or "")]
        for node in _json_ld_nodes(json_ld_values):
            for value in _values(node.get("email")):
                email_sources.append({"value": value.lower(), "source_url": page_url, "source_type": "structured_data"})
            for value in _values(node.get("telephone")):
                phone_sources.append({"value": value, "source_url": page_url, "source_type": "structured_data"})
    email_sources = list({(item["value"], item["source_url"], item["source_type"]): item for item in email_sources}.values())
    phone_sources = list({(item["value"], item["source_url"], item["source_type"]): item for item in phone_sources}.values())
    usable_emails = {item.lower() for item in cleaned["emails"]}
    usable_phones = set(cleaned["phones"])
    email_sources = [item for item in email_sources if item["value"] in usable_emails]
    phone_sources = [item for item in phone_sources if item["value"] in usable_phones]

    completeness = min(100, sum((
        10 if unique_names else 0,
        10 if domain else 0,
        20 if cleaned["phones"] else 0,
        20 if cleaned["emails"] else 0,
        15 if unique_addresses else 0,
        25 if unique_people else 0,
    )))

    return {
        "business_names": unique_names,
        "emails": cleaned["emails"],
        "email_validation": email_validation,
        "email_sources": email_sources,
        "phones": cleaned["phones"],
        "phone_verification": phone_verification,
        "phone_sources": phone_sources,
        "addresses": unique_addresses,
        "people": unique_people,
        "directory_contacts": unique_directory_contacts,
        "completeness_score": completeness,
    }
