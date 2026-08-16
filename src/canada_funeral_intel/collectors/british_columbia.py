from __future__ import annotations

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

BRITISH_COLUMBIA_SOURCE_NAME = "Consumer Protection BC Funeral Services Register"
BRITISH_COLUMBIA_REGISTER_URL = (
    "https://www.consumerprotectionbc.ca/check-a-licence-search/"
    "?cpbc_city=&cpbc_licenseNumber=&cpbc_name="
    "&cpbc_statuses=DUEPRT%2CEXEMPT%2CISSUED%2CNOTICE%2CRENSUBD%2CSUSPEND"
    "&cpbc_type=funeral"
)
DEFAULT_USER_AGENT = "CanadaFuneralIntel/0.1"
DEFAULT_TIMEOUT_SECONDS = 20.0


class BritishColumbiaCollectorError(RuntimeError):
    """Raised when the BC public register cannot be collected safely."""


@dataclass(frozen=True, slots=True)
class BritishColumbiaFuneralProvider:
    source_ordinal: int
    licence_number: str
    legal_name: str
    trade_name: str | None
    address: str | None
    city: str | None
    initial_issue_date: str | None
    licence_expiry_date: str | None
    licence_status: str

    @property
    def external_record_id(self) -> str:
        return f"BC-{self.licence_number}"

    def as_payload(self) -> dict[str, object]:
        return {
            "licence_type": "Funeral Services",
            "licence_number": self.licence_number,
            "legal_name": self.legal_name,
            "trade_name": self.trade_name,
            "address": self.address,
            "city": self.city,
            "province": "BC",
            "initial_issue_date": self.initial_issue_date,
            "licence_expiry_date": self.licence_expiry_date,
            "licence_status": self.licence_status,
            "source_ordinal": self.source_ordinal,
        }


class _LicenceTableParser(HTMLParser):
    """Parse only the public register table, ignoring surrounding page HTML."""

    _HEADERS = (
        "licence type",
        "licence number",
        "business name",
        "does business as",
        "address",
        "initial issue date",
        "licence expiry date",
        "licence status",
    )

    def __init__(self) -> None:
        super().__init__()
        self._in_table = False
        self._in_row = False
        self._in_cell = False
        self._cell_parts: list[str] = []
        self._row: list[str] = []
        self.headers: tuple[str, ...] | None = None
        self.rows: list[tuple[str, ...]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table" and any(
            name == "class" and value and "cpbc-data-query-results" in value
            for name, value in attrs
        ):
            self._in_table = True
        if not self._in_table:
            return
        if tag == "tr":
            self._in_row = True
            self._row = []
        elif tag in {"th", "td"} and self._in_row:
            self._in_cell = True
            self._cell_parts = []

    def handle_endtag(self, tag: str) -> None:
        if not self._in_table:
            return
        if tag in {"th", "td"} and self._in_cell:
            self._row.append(" ".join("".join(self._cell_parts).split()))
            self._in_cell = False
        elif tag == "tr" and self._in_row:
            if self.headers is None and self._row:
                self.headers = tuple(item.casefold() for item in self._row)
            elif self._row:
                self.rows.append(tuple(self._row))
            self._in_row = False
        elif tag == "table":
            self._in_table = False

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_parts.append(data)


def fetch_register(
    *,
    url: str = BRITISH_COLUMBIA_REGISTER_URL,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> bytes:
    request = Request(
        url,
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
        raise BritishColumbiaCollectorError(
            f"Unable to fetch British Columbia register: {exc}"
        ) from exc

    if not body or content_type not in {"text/html", "application/xhtml+xml"}:
        raise BritishColumbiaCollectorError(
            "British Columbia register did not return HTML "
            f"(content type {content_type!r})"
        )
    return body


def parse_register(html: str) -> tuple[BritishColumbiaFuneralProvider, ...]:
    parser = _LicenceTableParser()
    parser.feed(html)
    if parser.headers != _LicenceTableParser._HEADERS:
        raise BritishColumbiaCollectorError(
            "British Columbia register table headers were not found"
        )

    records: list[BritishColumbiaFuneralProvider] = []
    for source_ordinal, row in enumerate(parser.rows, start=1):
        if len(row) != len(parser.headers):
            raise BritishColumbiaCollectorError(
                f"British Columbia register row {source_ordinal} has "
                f"{len(row)} columns, expected {len(parser.headers)}"
            )
        (
            licence_type,
            licence_number,
            legal_name,
            trade_name,
            address,
            initial,
            expiry,
            status,
        ) = row
        if licence_type.casefold() != "funeral services":
            continue
        if not licence_number or not legal_name or not status:
            raise BritishColumbiaCollectorError(
                f"British Columbia register row {source_ordinal} is incomplete"
            )
        records.append(
            BritishColumbiaFuneralProvider(
                source_ordinal=source_ordinal,
                licence_number=licence_number,
                legal_name=legal_name,
                trade_name=trade_name or None,
                address=address or None,
                city=_city_from_address(address),
                initial_issue_date=initial or None,
                licence_expiry_date=expiry or None,
                licence_status=status,
            )
        )

    if not records:
        raise BritishColumbiaCollectorError(
            "British Columbia register contained no funeral-service rows"
        )
    return tuple(records)


def records_as_parse_result(
    records: tuple[BritishColumbiaFuneralProvider, ...],
) -> ParseResult:
    rows: list[ImportRow] = []
    for record in records:
        raw_payload = json.dumps(
            record.as_payload(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=False,
        )
        rows.append(
            ImportRow(
                row_number=record.source_ordinal,
                raw_payload=raw_payload,
                checksum=payload_checksum(raw_payload),
                external_record_id=record.external_record_id,
            )
        )
    return ParseResult(rows=tuple(rows), errors=())


def collect_parse_result(
    *,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> ParseResult:
    body = fetch_register(
        user_agent=user_agent,
        timeout_seconds=timeout_seconds,
    )
    return records_as_parse_result(
        parse_register(body.decode("utf-8", errors="strict"))
    )


def _city_from_address(address: str) -> str | None:
    match = re.search(r"\s+([A-Z][A-Z .'-]+)\s+BC\s+[A-Z]\d[A-Z]\d[A-Z]\d$", address)
    return match.group(1).strip().title() if match else None
