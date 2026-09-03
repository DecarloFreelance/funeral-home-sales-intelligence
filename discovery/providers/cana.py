import re
import time
from typing import Dict, List
from urllib.parse import urlencode, urljoin

import requests

def _extract_province_improved(text):
    """Extract province from address or text."""
    if not text:
        return None
    text = str(text).upper().strip()
    pattern1 = r'\b([A-Z]{2})\s+[A-Z]\d[A-Z]\s*\d[A-Z]\d\b'
    match = re.search(pattern1, text)
    if match:
        return match.group(1)
    pattern2 = r',\s*([A-Z]{2})\b'
    match = re.search(pattern2, text)
    if match:
        return match.group(1)
    province_names = {
        'ALBERTA': 'AB', 'BRITISH COLUMBIA': 'BC', 'MANITOBA': 'MB',
        'NEW BRUNSWICK': 'NB', 'NEWFOUNDLAND': 'NL', 'NOVA SCOTIA': 'NS',
        'NORTHWEST TERRITORIES': 'NT', 'NUNAVUT': 'NU', 'ONTARIO': 'ON',
        'PRINCE EDWARD ISLAND': 'PE', 'QUEBEC': 'QC', 'SASKATCHEWAN': 'SK',
        'YUKON': 'YT'
    }
    for name, code in province_names.items():
        if name in text:
            return code
    return None


from bs4 import BeautifulSoup, SoupStrainer


DIRECTORY_BASE = "https://members.cremationassociation.org/canamembers/results"
TARGET_CATEGORIES = {"Funeral Home", "Mortuary", "Crematory"}
USER_AGENT = (
    "Mozilla/5.0 (compatible; FuneralHomeSalesIntelligence/1.0; "
    "+https://cremationassociation.org/)"
)


def directory_url(country="Canada"):
    return f"{DIRECTORY_BASE}?{urlencode({'Country': country})}"


def _text(container, selector):
    node = container.select_one(selector)
    return node.get_text(" ", strip=True) if node else ""



def parse_results(html: str, source_url: str) -> List[Dict[str, str]]:
    # CANA's country-wide pages are large (the US result is over 13 MB). lxml
    # avoids the prohibitive runtime of Python's built-in HTML parser here.
    soup = BeautifulSoup(
        html,
        "lxml",
        parse_only=SoupStrainer(
            "div",
            class_=lambda value: value and "ListingResults_All_CONTAINER" in value,
        ),
    )
    records = []
    for item in soup.select(".ListingResults_All_CONTAINER"):
        name = item.select_one('[itemprop="name"]')
        if not name:
            continue
        company = name.get_text(" ", strip=True)
        profile = name.find("a", href=True)
        listing_url = urljoin(source_url, profile["href"]) if profile else source_url
        visit = item.select_one(".ListingResults_Level3_VISITSITE a[href]")
        categories = [
            node.get("title", "").strip()
            for node in item.select(".ListingResults_Level3_AFFILIATIONICON[title]")
            if node.get("title", "").strip()
        ]
        contact_node = item.select_one(".ListingResults_Level3_MAINCONTACT")
        contact = contact_node.get_text(" ", strip=True) if contact_node else ""
        
        # Extract province from region or address
        province = _text(item, '[itemprop="region"]')
        if not province:
            address = _text(item, '[itemprop="street-address"]')
            if address:
                province = _extract_province_improved(address)
        
        records.append({
            "company": company,
            "website": visit["href"].strip() if visit else "",
            "city": _text(item, '[itemprop="locality"]'),
            "province": province,
            "country": "Canada" if "Canada" in item.get_text(" ", strip=True) else "United States",
            "phone": _text(item, ".ListingResults_Level3_PHONE1"),
            "email": "",
            "address": _text(item, '[itemprop="street-address"]'),
            "postal_code": _text(item, '[itemprop="postal-code"]'),
            "contact_name": contact,
            "category": ", ".join(categories) or "deathcare_provider",
            "source": "association",
            "source_name": "Cremation Association of North America",
            "source_url": listing_url,
        })
    return records
def is_target_provider(record):
    categories = {value.strip() for value in record.get("category", "").split(",")}
    return bool(categories & TARGET_CATEGORIES)


class CanaDirectoryClient:
    def __init__(self, session=None, timeout=30, delay=0.5, retries=2):
        self.session = session or requests.Session()
        self.timeout = timeout
        self.delay = delay
        self.retries = retries
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-CA,en;q=0.9",
        })

    def fetch(self, countries=("Canada",), target_only=True) -> List[Dict[str, str]]:
        records = []
        for index, country in enumerate(countries):
            if index and self.delay:
                time.sleep(self.delay)
            url = directory_url(country)
            response = None
            for attempt in range(self.retries + 1):
                try:
                    response = self.session.get(url, timeout=self.timeout)
                    response.raise_for_status()
                    break
                except requests.RequestException:
                    if attempt >= self.retries:
                        raise
                    time.sleep(min(4, 2 ** attempt))
            parsed = parse_results(response.text, url)
            if not parsed:
                raise ValueError(f"CANA directory returned no records for {country}")
            if target_only:
                parsed = [record for record in parsed if is_target_provider(record)]
            records.extend(parsed)
        return records
