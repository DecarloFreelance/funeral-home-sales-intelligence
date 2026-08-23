from dataclasses import asdict, dataclass, field
import re
from typing import Dict, Iterable, List
from urllib.parse import urlsplit, urlunsplit

from discovery.network_safety import static_public_hostname


PRIORITY_PATHS = (
    "/contact",
    "/contact-us",
    "/about",
    "/team",
    "/staff",
    "/funeral-directors",
    "/locations",
)


def normalize_website(value: str) -> str:
    website = (value or "").strip()
    if not website:
        return ""

    explicit_scheme = re.match(r"^[a-z][a-z0-9+.-]*:", website, re.I)
    if explicit_scheme and not website.lower().startswith(("http://", "https://")):
        return ""

    if "://" not in website:
        website = f"https://{website}"

    parsed = urlsplit(website)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return ""

    host = parsed.hostname.lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if "." not in host:
        return ""
    if not static_public_hostname(host):
        return ""

    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return ""

    try:
        port = f":{parsed.port}" if parsed.port else ""
    except ValueError:
        return ""
    return urlunsplit((parsed.scheme.lower(), host + port, "/", "", ""))


def domain_from_website(website: str) -> str:
    normalized = normalize_website(website)
    if not normalized:
        return ""
    return urlsplit(normalized).hostname or ""


@dataclass
class DiscoveryLead:
    company: str
    website: str
    city: str = ""
    province: str = ""
    country: str = "Canada"
    phone: str = ""
    email: str = ""
    address: str = ""
    category: str = "funeral_home"
    source: str = "manual"
    source_url: str = ""
    contact_name: str = ""
    contact_title: str = ""
    domain: str = field(init=False)

    def __post_init__(self):
        self.company = self.company.strip()
        self.website = normalize_website(self.website)
        self.domain = domain_from_website(self.website)
        self.city = self.city.strip()
        self.province = self.province.strip().upper()
        self.country = self.country.strip() or "Canada"
        self.phone = self.phone.strip()
        self.email = self.email.strip().lower()
        self.address = self.address.strip()
        self.category = self.category.strip() or "funeral_home"
        self.source = self.source.strip() or "manual"
        self.source_url = self.source_url.strip()
        self.contact_name = self.contact_name.strip()
        self.contact_title = self.contact_title.strip()

    @classmethod
    def from_mapping(cls, row: Dict[str, str]):
        return cls(
            company=row.get("company", ""),
            website=row.get("website", row.get("url", "")),
            city=row.get("city", ""),
            province=row.get("province", row.get("region", "")),
            country=row.get("country", "Canada"),
            phone=row.get("phone", ""),
            email=row.get("email", ""),
            address=row.get("address", ""),
            category=row.get("category", "funeral_home"),
            source=row.get("source", "manual"),
            source_url=row.get("source_url", ""),
            contact_name=row.get("contact_name", ""),
            contact_title=row.get("contact_title", ""),
        )

    def to_queue_record(self) -> Dict[str, object]:
        record = asdict(self)
        record["url"] = self.website
        record["sources"] = sorted(
            source for source in self.source.split(",") if source
        )
        record["priority_urls"] = [
            f"{self.website.rstrip('/')}{path}"
            for path in PRIORITY_PATHS
        ]
        record["status"] = "PENDING"
        return record


def _merge(existing: DiscoveryLead, incoming: DiscoveryLead) -> DiscoveryLead:
    values = {}
    for name in DiscoveryLead.__dataclass_fields__:
        if name == "domain":
            continue
        old_value = getattr(existing, name)
        new_value = getattr(incoming, name)
        values[name] = old_value or new_value

    sources = {existing.source, incoming.source}
    values["source"] = ",".join(sorted(source for source in sources if source))
    return DiscoveryLead(**values)


def build_crawl_queue(leads: Iterable[DiscoveryLead]) -> List[Dict[str, object]]:
    by_domain: Dict[str, DiscoveryLead] = {}
    provenance = {}
    locations = {}

    for lead in leads:
        if not lead.domain:
            continue
        provenance.setdefault(lead.domain, set()).add(
            (lead.source, lead.source_url)
        )
        locations.setdefault(lead.domain, {})[
            (
                lead.company.lower(),
                lead.address.lower(),
                lead.city.lower(),
                lead.province.lower(),
            )
        ] = {
            "company": lead.company,
            "address": lead.address,
            "city": lead.city,
            "province": lead.province,
            "country": lead.country,
            "phone": lead.phone,
            "email": lead.email,
            "source_url": lead.source_url,
            "contact_name": lead.contact_name,
            "contact_title": lead.contact_title,
        }
        if lead.domain in by_domain:
            by_domain[lead.domain] = _merge(by_domain[lead.domain], lead)
        else:
            by_domain[lead.domain] = lead

    queue = []
    for domain in sorted(by_domain):
        record = by_domain[domain].to_queue_record()
        record["provenance"] = [
            {"source": source, "source_url": source_url}
            for source, source_url in sorted(provenance[domain])
        ]
        record["locations"] = list(locations[domain].values())
        record["business_names"] = list(dict.fromkeys(
            location["company"]
            for location in record["locations"]
            if location["company"]
        ))
        queue.append(record)
    return queue
