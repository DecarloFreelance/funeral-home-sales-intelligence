from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from canada_funeral_intel.collectors.importers import (
    ImportRow,
    ParseResult,
    payload_checksum,
)

MANITOBA_SOURCE_NAME = "Funeral Board of Manitoba"
MANITOBA_DIRECTORY_URL = "https://www.gov.mb.ca/funeraldirectorsboard/homes.html"
MANITOBA_PDF_URL = (
    "https://www.gov.mb.ca/funeraldirectorsboard/pdf/2026_licenced_funeral_homes.pdf"
)
DEFAULT_USER_AGENT = "CanadaFuneralIntel/0.1"
DEFAULT_TIMEOUT_SECONDS = 20.0


class ManitobaCollectorError(RuntimeError):
    """Raised when the Manitoba public source cannot be collected safely."""


@dataclass(frozen=True, slots=True)
class ManitobaFuneralHome:
    source_ordinal: int
    source_line: int
    source_year: int
    name: str
    address: str | None
    city: str
    province: str
    phone: str | None
    email: str | None

    @property
    def external_record_id(self) -> str:
        return f"MB-{self.source_year}-{self.source_ordinal:03d}"

    def as_payload(self) -> dict[str, object]:
        return {
            "name": self.name,
            "address": self.address,
            "city": self.city,
            "province": self.province,
            "phone": self.phone,
            "email": self.email,
            "source_year": self.source_year,
            "source_ordinal": self.source_ordinal,
            "source_line": self.source_line,
        }


def fetch_pdf(
    *,
    url: str = MANITOBA_PDF_URL,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> bytes:
    request = Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/pdf,*/*;q=0.8",
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read()
            content_type = response.headers.get_content_type()
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise ManitobaCollectorError(f"Unable to fetch Manitoba PDF: {exc}") from exc

    if not body.startswith(b"%PDF-"):
        raise ManitobaCollectorError(
            f"Manitoba source did not return a PDF (content type {content_type!r})"
        )
    return body


def extract_pdf_text(pdf_bytes: bytes) -> str:
    executable = shutil.which("pdftotext")
    if executable is None:
        raise ManitobaCollectorError(
            "pdftotext is required to parse the Manitoba regulatory PDF"
        )

    with tempfile.TemporaryDirectory(prefix="cfi-manitoba-") as directory:
        pdf_path = Path(directory) / "source.pdf"
        text_path = Path(directory) / "source.txt"
        pdf_path.write_bytes(pdf_bytes)

        result = subprocess.run(
            [executable, "-layout", str(pdf_path), str(text_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or f"exit status {result.returncode}"
            raise ManitobaCollectorError(f"pdftotext failed: {detail}")

        try:
            return text_path.read_text(encoding="utf-8", errors="strict")
        except OSError as exc:
            raise ManitobaCollectorError(
                f"Unable to read extracted Manitoba text: {exc}"
            ) from exc


def parse_funeral_homes(text: str) -> tuple[ManitobaFuneralHome, ...]:
    declared_match = re.search(
        r"Total Licenced Funeral Homes for (\d{4}):\s*(\d+)",
        text,
        flags=re.IGNORECASE,
    )
    if declared_match is None:
        raise ManitobaCollectorError(
            "Manitoba PDF declared funeral-home total was not found"
        )

    source_year = int(declared_match.group(1))
    declared_total = int(declared_match.group(2))
    labels = ("Funeral Home", "Address", "City", "Phone", "Email")
    positions: tuple[int, int, int, int, int] | None = None
    header_count = 0
    records: list[ManitobaFuneralHome] = []

    for source_line, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue

        if all(label in line for label in labels):
            candidate = tuple(line.find(label) for label in labels)
            if any(position < 0 for position in candidate):
                raise ManitobaCollectorError("Invalid Manitoba PDF table header")
            if candidate != tuple(sorted(candidate)):
                raise ManitobaCollectorError("Invalid Manitoba PDF column order")
            positions = candidate
            header_count += 1
            continue

        lower = stripped.casefold()
        if lower.startswith(f"licenced funeral homes for {source_year}"):
            continue
        if lower.startswith("as of ") and "page " in lower:
            continue
        if lower.startswith(f"total licenced funeral homes for {source_year}:"):
            continue
        if positions is None:
            continue

        name_pos, address_pos, city_pos, phone_pos, email_pos = positions
        if not line[:address_pos].strip():
            fragment = line[email_pos:].strip() if len(line) > email_pos else stripped
            if fragment and records:
                previous = records[-1]
                email = _clean_email((previous.email or "") + fragment)
                records[-1] = ManitobaFuneralHome(
                    source_ordinal=previous.source_ordinal,
                    source_line=previous.source_line,
                    source_year=previous.source_year,
                    name=previous.name,
                    address=previous.address,
                    city=previous.city,
                    province=previous.province,
                    phone=previous.phone,
                    email=email,
                )
            continue

        padded = line.ljust(email_pos)
        name = _clean(padded[name_pos:address_pos])
        city = _clean(padded[city_pos:phone_pos])
        if name is None:
            continue
        if city is None:
            raise ManitobaCollectorError(
                f"Manitoba source row {source_line} has no city"
            )

        records.append(
            ManitobaFuneralHome(
                source_ordinal=len(records) + 1,
                source_line=source_line,
                source_year=source_year,
                name=name,
                address=_clean(padded[address_pos:city_pos]),
                city=city,
                province="MB",
                phone=_clean(padded[phone_pos:email_pos]),
                email=_clean_email(line[email_pos:] if len(line) > email_pos else ""),
            )
        )

    if header_count < 1:
        raise ManitobaCollectorError("No Manitoba PDF table headers were found")
    if len(records) != declared_total:
        raise ManitobaCollectorError(
            "Parsed Manitoba row count does not match declared total: "
            f"{len(records)} != {declared_total}"
        )

    return tuple(records)


def records_as_parse_result(
    records: tuple[ManitobaFuneralHome, ...],
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
    pdf = fetch_pdf(
        user_agent=user_agent,
        timeout_seconds=timeout_seconds,
    )
    text = extract_pdf_text(pdf)
    return records_as_parse_result(parse_funeral_homes(text))


def _clean(value: str) -> str | None:
    value = re.sub(r"\s+", " ", value).strip()
    return value or None


def _clean_email(value: str) -> str | None:
    value = _clean(value)
    if value is None:
        return None
    value = value.replace("\\:", ":")
    markdown = re.fullmatch(
        r"\[([^\]]+)\]\(mailto:\\?:?([^)]+)\)",
        value,
        flags=re.IGNORECASE,
    )
    if markdown:
        value = markdown.group(2)
    value = _clean(value)
    if value is None:
        return None
    if (
        re.fullmatch(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", value, re.IGNORECASE)
        is None
    ):
        raise ManitobaCollectorError(f"Invalid Manitoba email value: {value!r}")
    return value
