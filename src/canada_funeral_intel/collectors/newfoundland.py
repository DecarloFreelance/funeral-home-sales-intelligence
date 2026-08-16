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

NEWFOUNDLAND_SOURCE_NAME = (
    "Newfoundland and Labrador Embalmers and Funeral Directors Board "
    "Registered Funeral Homes"
)
NEWFOUNDLAND_DIRECTORY_URL = "https://www.nlfuneralboard.ca/funeral-homes"
DEFAULT_USER_AGENT = "CanadaFuneralIntel/0.1"
DEFAULT_TIMEOUT_SECONDS = 20.0


class NewfoundlandCollectorError(RuntimeError):
    """Raised when the Newfoundland and Labrador directory cannot be parsed."""


@dataclass(frozen=True, slots=True)
class NewfoundlandFuneralHome:
    source_ordinal: int
    name: str
    address: str
    city: str

    @property
    def external_record_id(self) -> str:
        key = f"{self.name}|{self.address}".encode()
        return f"NL-{hashlib.sha256(key).hexdigest()[:16]}"

    def as_payload(self) -> dict[str, object]:
        return {
            "name": self.name,
            "address": self.address,
            "city": self.city,
            "province": "NL",
            "source_ordinal": self.source_ordinal,
        }


class _DirectoryParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_paragraph = False
        self._parts: list[str] = []
        self.paragraphs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br" and self._in_paragraph:
            self._parts.append("\n")
        elif tag == "p":
            self._in_paragraph = True
            self._parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag != "p" or not self._in_paragraph:
            return
        value = html.unescape("".join(self._parts))
        value = " | ".join(
            part.strip() for part in re.split(r"\s*\n\s*", value) if part.strip()
        )
        value = re.sub(r"\s+", " ", value).strip()
        if value:
            self.paragraphs.append(value)
        self._in_paragraph = False
        self._parts = []

    def handle_data(self, data: str) -> None:
        if self._in_paragraph:
            self._parts.append(data)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br" and self._in_paragraph:
            self._parts.append("\n")


def fetch_directory(
    *,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> str:
    request = Request(
        NEWFOUNDLAND_DIRECTORY_URL,
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
        raise NewfoundlandCollectorError(
            f"Unable to fetch Newfoundland and Labrador directory: {exc}"
        ) from exc
    if content_type not in {"text/html", "application/xhtml+xml"}:
        raise NewfoundlandCollectorError(
            f"Newfoundland and Labrador directory did not return HTML: {content_type!r}"
        )
    return body.decode("utf-8", errors="strict")


def parse_directory(text: str) -> tuple[NewfoundlandFuneralHome, ...]:
    parser = _DirectoryParser()
    parser.feed(text)
    records: list[NewfoundlandFuneralHome] = []
    name: str | None = None
    address_lines: list[str] = []

    for raw_paragraph in parser.paragraphs:
        for paragraph in raw_paragraph.split(" | "):
            paragraph = paragraph.replace("\u200b", "").strip()
            if not paragraph or _is_contact_line(paragraph):
                continue
            if _looks_like_postal_address(paragraph):
                if name is None:
                    name, address = _split_name_address(paragraph)
                    address_lines = [address] if address else []
                else:
                    address_lines.append(paragraph)
                if name is not None:
                    address = ", ".join(address_lines)
                    records.append(
                        NewfoundlandFuneralHome(
                            source_ordinal=len(records) + 1,
                            name=name,
                            address=address,
                            city=_city_from_address(paragraph),
                        )
                    )
                name = None
                address_lines = []
                continue
            paragraph = re.sub(r"\s*Phone:\s*\(\d{3}\)[^,;]*", "", paragraph)
            if name is None:
                name, address = _split_name_address(paragraph)
                if address:
                    address_lines.append(address)
            else:
                address_lines.append(paragraph)

    if not records:
        raise NewfoundlandCollectorError(
            "Newfoundland and Labrador directory contained no funeral homes"
        )
    return tuple(records)


def records_as_parse_result(
    records: tuple[NewfoundlandFuneralHome, ...],
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


def _looks_like_postal_address(value: str) -> bool:
    return bool(re.search(r"\bNL\s+[A-Z]\d[A-Z]\s?\d[A-Z]\d\b", value, re.IGNORECASE))


def _city_from_address(address: str) -> str:
    match = re.search(
        r"([^,]+),\s*NL\s+[A-Z]\d[A-Z]\s?\d[A-Z]\d\b",
        address,
        re.IGNORECASE,
    )
    return match.group(1).strip() if match else ""


def _is_contact_line(value: str) -> bool:
    return value.casefold().startswith(("phone:", "e-mail:", "email:"))


def _split_name_address(value: str) -> tuple[str, str]:
    match = re.search(r"\s+(?=(?:P\.?\s*O\.?\s+Box|\d+\s))", value)
    if not match:
        return value, ""
    return value[: match.start()].strip(), value[match.end() :].strip()
