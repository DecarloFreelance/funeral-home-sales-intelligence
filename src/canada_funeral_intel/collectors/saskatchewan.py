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

SASKATCHEWAN_SOURCE_NAME = (
    "Funeral and Cremation Services Council of Saskatchewan Roster"
)
SASKATCHEWAN_ROSTER_URL = "https://fcscs.ca/roster/"
DEFAULT_USER_AGENT = "CanadaFuneralIntel/0.1"
DEFAULT_TIMEOUT_SECONDS = 20.0
_LICENSE_CODES = {"FH", "FHC"}


class SaskatchewanCollectorError(RuntimeError):
    """Raised when the Saskatchewan roster cannot be collected safely."""


@dataclass(frozen=True, slots=True)
class SaskatchewanFuneralHome:
    source_ordinal: int
    name: str
    license_code: str
    license_number: str
    city: str

    @property
    def external_record_id(self) -> str:
        return f"SK-{self.license_number}"

    def as_payload(self) -> dict[str, object]:
        return {
            "name": self.name,
            "license_code": self.license_code,
            "license_number": self.license_number,
            "city": self.city,
            "province": "SK",
            "source_ordinal": self.source_ordinal,
        }


def fetch_pdf(
    *,
    url: str = SASKATCHEWAN_ROSTER_URL,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> bytes:
    request = Request(
        url, headers={"User-Agent": user_agent, "Accept": "application/pdf,*/*;q=0.8"}
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read()
            content_type = response.headers.get_content_type()
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise SaskatchewanCollectorError(
            f"Unable to fetch Saskatchewan roster: {exc}"
        ) from exc
    if not body.startswith(b"%PDF-"):
        raise SaskatchewanCollectorError(
            f"Saskatchewan roster did not return a PDF (content type {content_type!r})"
        )
    return body


def extract_pdf_text(pdf_bytes: bytes) -> str:
    executable = shutil.which("pdftotext")
    if executable is None:
        raise SaskatchewanCollectorError(
            "pdftotext is required to parse the Saskatchewan roster"
        )
    with tempfile.TemporaryDirectory(prefix="cfi-saskatchewan-") as directory:
        pdf_path = Path(directory) / "roster.pdf"
        text_path = Path(directory) / "roster.txt"
        pdf_path.write_bytes(pdf_bytes)
        result = subprocess.run(
            [executable, "-layout", str(pdf_path), str(text_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or f"exit status {result.returncode}"
            raise SaskatchewanCollectorError(f"pdftotext failed: {detail}")
        try:
            return text_path.read_text(encoding="utf-8", errors="strict")
        except OSError as exc:
            raise SaskatchewanCollectorError(
                f"Unable to read extracted Saskatchewan roster: {exc}"
            ) from exc


def parse_roster(text: str) -> tuple[SaskatchewanFuneralHome, ...]:
    start = text.find("FUNERAL HOMES, CREMATORIUMS, TRANSFER SERVICES")
    end = text.find("FUNERAL HOME LICENSES CANCELLED", start)
    if start < 0 or end < 0:
        raise SaskatchewanCollectorError(
            "Saskatchewan funeral-business roster section was not found"
        )
    records: list[SaskatchewanFuneralHome] = []
    for line in text[start:end].splitlines():
        for name, code, number, city in _parse_columns(line):
            if code not in _LICENSE_CODES:
                continue
            if not number.isdigit() or not name or not city:
                raise SaskatchewanCollectorError(
                    f"Invalid Saskatchewan roster row: {line!r}"
                )
            records.append(
                SaskatchewanFuneralHome(
                    source_ordinal=len(records) + 1,
                    name=name,
                    license_code=code,
                    license_number=number,
                    city=city,
                )
            )
    if not records:
        raise SaskatchewanCollectorError(
            "Saskatchewan roster contained no funeral-home licenses"
        )
    return tuple(records)


def records_as_parse_result(
    records: tuple[SaskatchewanFuneralHome, ...],
) -> ParseResult:
    rows: list[ImportRow] = []
    for record in records:
        raw_payload = json.dumps(
            record.as_payload(), ensure_ascii=False, separators=(",", ":")
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
    return records_as_parse_result(
        parse_roster(
            extract_pdf_text(
                fetch_pdf(user_agent=user_agent, timeout_seconds=timeout_seconds)
            )
        )
    )


def _parse_columns(line: str) -> tuple[tuple[str, str, str, str], ...]:
    if len(line) < 64 or "NAME" in line[:20].upper():
        return ()
    columns = (
        _parse_column(line[0:49], line[50:56], line[56:63], line[63:85]),
        _parse_column(line[85:140], line[141:147], line[147:154], line[154:]),
    )
    return tuple(item for item in columns if item is not None)


def _parse_column(
    name: str, code: str, number: str, city: str
) -> tuple[str, str, str, str] | None:
    cleaned = tuple(
        re.sub(r"\s+", " ", value).strip() for value in (name, code, number, city)
    )
    if not any(cleaned) or not cleaned[1] or not cleaned[2]:
        return None
    return cleaned
