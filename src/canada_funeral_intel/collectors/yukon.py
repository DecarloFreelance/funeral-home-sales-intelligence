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

YUKON_SOURCE_NAME = "Heritage North Funeral Home Official Contact Directory"
YUKON_DIRECTORY_URL = "https://heritagenorth.ca/contact/"
DEFAULT_USER_AGENT = "CanadaFuneralIntel/0.1"
DEFAULT_TIMEOUT_SECONDS = 20.0


class YukonCollectorError(RuntimeError):
    """Raised when the Yukon source cannot be parsed safely."""


@dataclass(frozen=True, slots=True)
class YukonFuneralHome:
    name: str
    address: str
    city: str

    @property
    def external_record_id(self) -> str:
        key = f"{self.name}|{self.address}".encode()
        return f"YT-{hashlib.sha256(key).hexdigest()[:16]}"

    def as_payload(self) -> dict[str, object]:
        return {
            "name": self.name,
            "address": self.address,
            "city": self.city,
            "province": "YT",
        }


class _ContactParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._tag: str | None = None
        self._parts: list[str] = []
        self.blocks: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"h5", "p"}:
            self._tag = tag
            self._parts = []
        elif tag == "br" and self._tag == "p":
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag != self._tag:
            return
        value = html.unescape("".join(self._parts))
        value = " | ".join(
            part.strip() for part in re.split(r"\s*\n\s*", value) if part.strip()
        )
        value = re.sub(r"\s+", " ", value).strip()
        if value:
            self.blocks.append((self._tag, value))
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
        YUKON_DIRECTORY_URL,
        headers={"User-Agent": user_agent, "Accept": "text/html,*/*;q=0.8"},
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read()
            content_type = response.headers.get_content_type()
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise YukonCollectorError(f"Unable to fetch Yukon source: {exc}") from exc
    if content_type not in {"text/html", "application/xhtml+xml"}:
        raise YukonCollectorError(f"Yukon source did not return HTML: {content_type!r}")
    return body.decode("utf-8", errors="strict")


def parse_directory(text: str) -> tuple[YukonFuneralHome, ...]:
    parser = _ContactParser()
    parser.feed(text)
    name: str | None = None
    records: list[YukonFuneralHome] = []
    for tag, value in parser.blocks:
        if tag == "h5" and "heritage north" in value.casefold():
            name = value
        elif (
            tag == "p"
            and name
            and re.search(r"\b(?:YT|Yukon),?\s+Y1A\s+3Z1\b", value, re.IGNORECASE)
        ):
            city_match = re.search(r"([^|,]+),\s*Yukon", value)
            if city_match:
                records.append(
                    YukonFuneralHome(
                        name=name,
                        address=value,
                        city=city_match.group(1).strip(),
                    )
                )
                name = None
    if not records:
        raise YukonCollectorError("Yukon source contained no funeral-home address")
    return tuple(records)


def records_as_parse_result(records: tuple[YukonFuneralHome, ...]) -> ParseResult:
    rows: list[ImportRow] = []
    for ordinal, record in enumerate(records, start=1):
        raw_payload = json.dumps(
            record.as_payload(), ensure_ascii=False, separators=(",", ":")
        )
        rows.append(
            ImportRow(
                ordinal,
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
