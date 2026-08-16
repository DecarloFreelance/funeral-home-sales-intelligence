from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from canada_funeral_intel.collectors.importers import (
    ImportRow,
    ParseResult,
    payload_checksum,
)

NEW_BRUNSWICK_SOURCE_NAME = (
    "New Brunswick Funeral Directors Association Member Directory"
)
NEW_BRUNSWICK_DIRECTORY_URL = "https://www.nbfuneraldirectors.ca/find-funeral-home/"
DEFAULT_USER_AGENT = "CanadaFuneralIntel/0.1"
DEFAULT_TIMEOUT_SECONDS = 20.0


class NewBrunswickCollectorError(RuntimeError):
    """Raised when the New Brunswick association directory cannot be parsed."""


@dataclass(frozen=True, slots=True)
class NewBrunswickFuneralHome:
    source_ordinal: int
    name: str
    address: str
    city: str

    @property
    def external_record_id(self) -> str:
        key = f"{self.name}|{self.address}".encode()
        return f"NB-{hashlib.sha256(key).hexdigest()[:16]}"

    def as_payload(self) -> dict[str, object]:
        return {
            "name": self.name,
            "address": self.address,
            "city": self.city,
            "province": "NB",
            "source_ordinal": self.source_ordinal,
        }


class _DirectoryParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._tag: str | None = None
        self._parts: list[str] = []
        self._name: str | None = None
        self.records: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"h2", "h3"}:
            self._tag = tag
            self._parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag != self._tag:
            return
        value = re.sub(r"\s+", " ", html.unescape(" ".join(self._parts))).strip()
        if self._tag == "h2" and value:
            self._name = value
        elif self._tag == "h3" and self._name and _looks_like_address(value):
            self.records.append((self._name, value))
        self._tag = None
        self._parts = []

    def handle_data(self, data: str) -> None:
        if self._tag is not None:
            self._parts.append(data)


def fetch_directory(
    *,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> str:
    request = Request(
        NEW_BRUNSWICK_DIRECTORY_URL,
        headers={
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read()
            content_type = response.headers.get_content_type()
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise NewBrunswickCollectorError(
            f"Unable to fetch New Brunswick directory: {exc}"
        ) from exc
    if content_type not in {"text/html", "application/xhtml+xml"}:
        raise NewBrunswickCollectorError(
            f"New Brunswick directory did not return HTML: {content_type!r}"
        )
    return body.decode("utf-8", errors="strict")


def parse_directory(text: str) -> tuple[NewBrunswickFuneralHome, ...]:
    parser = _DirectoryParser()
    parser.feed(text)
    records = tuple(
        NewBrunswickFuneralHome(
            source_ordinal=index,
            name=name,
            address=address,
            city=_city_from_address(address),
        )
        for index, (name, address) in enumerate(parser.records, start=1)
    )
    if not records:
        raise NewBrunswickCollectorError(
            "New Brunswick directory contained no member addresses"
        )
    return records


def records_as_parse_result(
    records: tuple[NewBrunswickFuneralHome, ...],
) -> ParseResult:
    rows: list[ImportRow] = []
    for record in records:
        raw_payload = json.dumps(
            record.as_payload(), ensure_ascii=False, separators=(",", ":")
        )
        rows.append(
            ImportRow(
                record.source_ordinal,
                raw_payload,
                payload_checksum(raw_payload),
                record.external_record_id,
            )
        )
    return ParseResult(rows=tuple(rows), errors=())


def collect_parse_result(
    *,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> ParseResult:
    return records_as_parse_result(
        parse_directory(
            fetch_directory(user_agent=user_agent, timeout_seconds=timeout_seconds)
        )
    )


def _looks_like_address(value: str) -> bool:
    return bool(
        re.search(r"\bNB\b.*\b[A-Z]\d[A-Z]\s?\d[A-Z]\d\b", value, re.IGNORECASE)
    )


def _city_from_address(address: str) -> str:
    match = re.search(
        r"(.+?)\s+NB,?\s+[A-Z]\d[A-Z]\s?\d[A-Z]\d\b",
        address,
        re.IGNORECASE,
    )
    if not match:
        return ""
    before_province = match.group(1).strip()
    if "," in before_province:
        return before_province.rsplit(",", 1)[-1].strip()
    return before_province.split()[-1]
