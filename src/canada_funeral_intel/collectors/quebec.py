from __future__ import annotations

import hashlib
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

QUEBEC_SOURCE_NAME = "Santé Québec Funeral Services Permit Directory"
QUEBEC_DIRECTORY_URL = (
    "https://cdn-contenu.quebec.ca/cdn-contenu/sante/documents/"
    "Systeme_et_services_de_sante/permis-autorisations-sante-quebec/"
    "liste-entreprises-services-funeraires.pdf"
)
DEFAULT_USER_AGENT = "CanadaFuneralIntel/0.1"
DEFAULT_TIMEOUT_SECONDS = 20.0


class QuebecCollectorError(RuntimeError):
    """Raised when the Quebec permit directory cannot be collected safely."""


@dataclass(frozen=True, slots=True)
class QuebecFuneralFacility:
    source_ordinal: int
    permit_number: str | None
    legal_name: str
    director_name: str | None
    phone: str | None
    status: str
    address: str
    city: str

    @property
    def external_record_id(self) -> str:
        if self.permit_number:
            return f"QC-{self.permit_number}-{self.source_ordinal:03d}"
        key = f"{self.legal_name}|{self.address}|{self.city}".encode()
        return f"QC-NO-PERMIT-{hashlib.sha256(key).hexdigest()[:16]}"

    def as_payload(self) -> dict[str, object]:
        return {
            "legal_name": self.legal_name,
            "permit_number": self.permit_number,
            "director_name": self.director_name,
            "phone": self.phone,
            "status": self.status,
            "address": self.address,
            "city": self.city,
            "province": "QC",
            "source_ordinal": self.source_ordinal,
        }


def fetch_pdf(
    *,
    url: str = QUEBEC_DIRECTORY_URL,
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
        raise QuebecCollectorError(
            f"Unable to fetch Quebec permit directory: {exc}"
        ) from exc
    if not body.startswith(b"%PDF-"):
        raise QuebecCollectorError(
            "Quebec permit directory did not return a PDF "
            f"(content type {content_type!r})"
        )
    return body


def extract_pdf_text(pdf_bytes: bytes) -> str:
    executable = shutil.which("pdftotext")
    if executable is None:
        raise QuebecCollectorError(
            "pdftotext is required to parse the Quebec permit directory"
        )
    with tempfile.TemporaryDirectory(prefix="cfi-quebec-") as directory:
        pdf_path = Path(directory) / "directory.pdf"
        text_path = Path(directory) / "directory.txt"
        pdf_path.write_bytes(pdf_bytes)
        result = subprocess.run(
            [executable, "-layout", str(pdf_path), str(text_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or f"exit status {result.returncode}"
            raise QuebecCollectorError(f"pdftotext failed: {detail}")
        try:
            return text_path.read_text(encoding="utf-8", errors="strict")
        except OSError as exc:
            raise QuebecCollectorError(
                f"Unable to read extracted Quebec directory: {exc}"
            ) from exc


def parse_directory(text: str) -> tuple[QuebecFuneralFacility, ...]:
    records: list[QuebecFuneralFacility] = []
    block: dict[str, object] | None = None
    facilities: list[tuple[str, str]] = []

    def flush() -> None:
        nonlocal block, facilities
        if block is None:
            return
        permit = str(block.get("permit", ""))
        name = str(block.get("name", ""))
        status = str(block.get("status", ""))
        if not name or not status:
            raise QuebecCollectorError(
                "Incomplete Quebec permit block: "
                f"name={name!r}, permit={permit!r}, status={status!r}"
            )
        if status.casefold() == "actif":
            locations = facilities or _primary_location(block)
            if not locations:
                raise QuebecCollectorError(f"Quebec permit has no facility: {permit}")
            for address, city in locations:
                records.append(
                    QuebecFuneralFacility(
                        source_ordinal=len(records) + 1,
                        permit_number=permit,
                        legal_name=name,
                        director_name=_optional(block.get("director")),
                        phone=_optional(block.get("phone")),
                        status=status,
                        address=address,
                        city=city,
                    )
                )
        block = None
        facilities = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("Dénomination sociale :"):
            flush()
            block = {"name": line.split(":", 1)[1].strip()}
            continue
        if block is None:
            continue
        if line.startswith("Numéro de permis :"):
            block["permit"] = line.split(":", 1)[1].strip() or None
        elif line.startswith("Nom directeur des services funéraires :"):
            block["director"] = line.split(":", 1)[1].strip()
        elif line.startswith("État du permis :"):
            block["status"] = line.split(":", 1)[1].strip()
        elif line.startswith("Téléphone :"):
            block["phone"] = line.split(":", 1)[1].strip()
        else:
            match = re.match(r"^(.+?)\s+,\s+(.+?)\s+\d{2}\s+-\s+.+$", line)
            if match:
                facilities.append((match.group(1).strip(), match.group(2).strip()))
            elif "permit" not in block and line and "," not in line:
                block["name"] = f"{block['name']} {line}".strip()
    flush()
    if not records:
        raise QuebecCollectorError("Quebec directory contained no active facilities")
    return tuple(records)


def records_as_parse_result(records: tuple[QuebecFuneralFacility, ...]) -> ParseResult:
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
        parse_directory(
            extract_pdf_text(
                fetch_pdf(user_agent=user_agent, timeout_seconds=timeout_seconds)
            )
        )
    )


def _primary_location(block: dict[str, object]) -> list[tuple[str, str]]:
    address = _optional(block.get("address"))
    city = _optional(block.get("city"))
    return [(address, city)] if address and city else []


def _optional(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
