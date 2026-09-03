import re

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


import time
from typing import Dict, List
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup


DIRECTORY_URL = "https://www.afsa.ca/funeral-provider-directory"
USER_AGENT = (
    "Mozilla/5.0 (compatible; FuneralHomeSalesIntelligence/1.0; "
    "+https://www.afsa.ca/)"
)
EMAIL_PATTERN = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
)


def parse_directory_pages(html: str, base_url: str = DIRECTORY_URL) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    host = urlsplit(base_url).hostname
    pages = []
    for anchor in soup.find_all("a", href=True):
        if "view list" not in anchor.get_text(" ", strip=True).lower():
            continue
        url = urljoin(base_url, anchor["href"])
        if urlsplit(url).hostname == host:
            pages.append(url)
    return list(dict.fromkeys(pages))


def _label_value(description, label: str) -> str:
    for paragraph in description.find_all("p"):
        text = paragraph.get_text(" ", strip=True)
        if text.lower().startswith(label.lower() + ":"):
            return text.split(":", 1)[1].strip()
    return ""


def parse_member_page(html: str, source_url: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    records = []

    for item in soup.select("li.accordion-item"):
        title = item.select_one(".accordion-title .title-text")
        description = item.select_one(".accordion-description")
        if not title or not description:
            continue

        company = title.get_text(" ", strip=True)
        row = item.find_parent(class_=lambda value: value and "dmRespRow" in value)
        city_heading = row.find("h3") if row else None
        city = city_heading.get_text(" ", strip=True) if city_heading else ""

        website = ""
        for anchor in description.find_all("a", href=True):
            href = anchor["href"].strip()
            if urlsplit(href).scheme in {"http", "https"}:
                website = href
                break

        paragraphs = description.find_all("p")
        address = ""
        for paragraph in paragraphs:
            text = paragraph.get_text(" ", strip=True)
            if text and not re.match(r"^(phone|fax|website|email)\s*:", text, re.I):
                address = text
                break

        email_match = EMAIL_PATTERN.search(description.get_text(" ", strip=True))
        # Extract province from address or city
        province = _extract_province_improved(address) or _extract_province_improved(city) or "AB"
        records.append({
            "company": company,
            "website": website,
            "city": city,
            "province": province,
            "country": "Canada",
            "phone": _label_value(description, "Phone"),
            "email": email_match.group(0) if email_match else "",
            "address": address,
            "category": "funeral_home",
            "source": "association",
            "source_name": "Alberta Funeral Service Association",
            "source_url": source_url,
        })

    return records


class AfsaDirectoryClient:

    def __init__(self, session=None, timeout=20, delay=0.5):
        self.session = session or requests.Session()
        self.timeout = timeout
        self.delay = delay
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-CA,en;q=0.9",
        })

    def _get(self, url: str) -> str:
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        return response.text

    def fetch(self) -> List[Dict[str, str]]:
        index_html = self._get(DIRECTORY_URL)
        pages = parse_directory_pages(index_html)
        if not pages:
            raise ValueError("AFSA directory index contained no member pages")

        records = []
        for index, page_url in enumerate(pages):
            if index and self.delay:
                time.sleep(self.delay)
            records.extend(parse_member_page(self._get(page_url), page_url))
        return records
