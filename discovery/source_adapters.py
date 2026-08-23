import csv
import io
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from discovery.ingestion import DiscoveryLead


FIELD_ALIASES = {
    "company": ("company", "business_name", "name", "title"),
    "website": ("website", "site", "business_website", "domain", "url"),
    "city": ("city", "locality", "town"),
    "province": ("province", "state", "region", "administrative_area"),
    "country": ("country", "country_name"),
    "phone": ("phone", "telephone", "phone_number"),
    "email": ("email", "email_address"),
    "address": ("address", "street_address", "full_address"),
    "category": ("category", "business_category", "type"),
    "source_url": ("source_url", "listing_url", "profile_url", "directory_url"),
    "contact_name": ("contact_name", "member_contact", "representative"),
    "contact_title": ("contact_title", "contact_role", "job_title"),
}


def _first_value(row: Dict[str, Any], aliases: Iterable[str]) -> str:
    lowered = {str(key).lower().strip(): value for key, value in row.items()}
    for alias in aliases:
        value = lowered.get(alias)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def adapt_record(row: Dict[str, Any], source: str) -> DiscoveryLead:
    normalized = {
        field: _first_value(row, aliases)
        for field, aliases in FIELD_ALIASES.items()
    }
    normalized["source"] = source
    normalized["country"] = normalized["country"] or "Canada"
    normalized["category"] = normalized["category"] or "funeral_home"

    # Maps and directory exports often use `url` for the listing rather than
    # the business website. Do not accidentally queue the provider itself.
    if source in {"maps", "association", "directory"}:
        explicit_website = _first_value(
            row,
            ("website", "site", "business_website", "domain"),
        )
        normalized["website"] = explicit_website
        if not normalized["source_url"]:
            normalized["source_url"] = _first_value(row, ("url",))

    return DiscoveryLead.from_mapping(normalized)


def _json_records(value: Any) -> List[Dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for key in ("results", "businesses", "items", "records", "data"):
            if isinstance(value.get(key), list):
                return [item for item in value[key] if isinstance(item, dict)]
        return [value]
    raise ValueError("JSON discovery source must contain records")


def load_source(path: Path, source: str) -> List[DiscoveryLead]:
    suffix = path.suffix.lower()
    return load_source_text(path.read_text(encoding="utf-8-sig"), suffix, source)


def load_source_text(text: str, suffix: str, source: str) -> List[DiscoveryLead]:
    suffix = suffix.lower()
    if suffix == ".csv":
        rows = list(csv.DictReader(io.StringIO(text)))
        if not rows and not text.strip():
            raise ValueError("Discovery source is empty")
    elif suffix == ".json":
        rows = _json_records(json.loads(text))
    else:
        raise ValueError(f"Unsupported discovery source format: {suffix}")

    return [adapt_record(row, source) for row in rows]


def parse_source_spec(spec: str):
    if "=" not in spec:
        raise ValueError("Source must use TYPE=PATH format")
    source, raw_path = spec.split("=", 1)
    source = source.strip().lower()
    path = Path(raw_path.strip())
    if not source or not raw_path.strip():
        raise ValueError("Source must use TYPE=PATH format")
    return source, path
