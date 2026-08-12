from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from enum import StrEnum

from canada_funeral_intel.storage.database import transaction


class WebsiteCheckError(ValueError):
    """Raised when website-check data is invalid."""


class WebsiteCheckStorageError(RuntimeError):
    """Raised when website-check persistence cannot complete safely."""


class DNSStatus(StrEnum):
    NOT_CHECKED = "not_checked"
    OK = "ok"
    FAILED = "failed"


class TLSStatus(StrEnum):
    NOT_CHECKED = "not_checked"
    OK = "ok"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"


class WebsiteCheckOutcome(StrEnum):
    UNKNOWN = "unknown"
    REACHABLE = "reachable"
    UNREACHABLE = "unreachable"
    MISMATCH = "mismatch"
    PARKED = "parked"


@dataclass(frozen=True, slots=True)
class WebsiteCheck:
    website_id: int
    requested_url: str
    final_url: str | None = None
    dns_status: DNSStatus = DNSStatus.NOT_CHECKED
    dns_addresses: tuple[str, ...] = ()
    tls_status: TLSStatus = TLSStatus.NOT_CHECKED
    tls_expires_at: str | None = None
    https_status_code: int | None = None
    http_status_code: int | None = None
    redirect_count: int = 0
    response_time_ms: int | None = None
    content_type: str | None = None
    canonical_url: str | None = None
    soft_404: bool = False
    parked_or_for_sale: bool = False
    identity_score: float | None = None
    outcome: WebsiteCheckOutcome = WebsiteCheckOutcome.UNKNOWN
    error_message: str | None = None

    def validate(self) -> None:
        if self.website_id < 1:
            raise WebsiteCheckError("website_id must be a positive integer")

        if not self.requested_url.strip():
            raise WebsiteCheckError("requested_url must not be empty")

        for label, value in (
            ("final_url", self.final_url),
            ("tls_expires_at", self.tls_expires_at),
            ("content_type", self.content_type),
            ("canonical_url", self.canonical_url),
            ("error_message", self.error_message),
        ):
            if value is not None and not value.strip():
                raise WebsiteCheckError(f"{label} must not be blank when provided")

        for label, value in (
            ("https_status_code", self.https_status_code),
            ("http_status_code", self.http_status_code),
        ):
            if value is not None and not 100 <= value <= 599:
                raise WebsiteCheckError(f"{label} must be between 100 and 599")

        if self.redirect_count < 0:
            raise WebsiteCheckError("redirect_count must not be negative")

        if self.response_time_ms is not None and self.response_time_ms < 0:
            raise WebsiteCheckError("response_time_ms must not be negative")

        if self.identity_score is not None and not 0.0 <= self.identity_score <= 1.0:
            raise WebsiteCheckError("identity_score must be between 0.0 and 1.0")

        for address in self.dns_addresses:
            if not address.strip():
                raise WebsiteCheckError("dns_addresses must not contain blank values")


@dataclass(frozen=True, slots=True)
class WebsiteCheckRecord:
    check_id: int
    website_id: int
    requested_url: str
    final_url: str | None
    dns_status: DNSStatus
    dns_addresses: tuple[str, ...]
    tls_status: TLSStatus
    tls_expires_at: str | None
    https_status_code: int | None
    http_status_code: int | None
    redirect_count: int
    response_time_ms: int | None
    content_type: str | None
    canonical_url: str | None
    soft_404: bool
    parked_or_for_sale: bool
    identity_score: float | None
    outcome: WebsiteCheckOutcome
    error_message: str | None
    checked_at: str


def insert_website_check(
    connection: sqlite3.Connection,
    check: WebsiteCheck,
) -> int:
    check.validate()

    addresses_json = json.dumps(
        list(check.dns_addresses),
        separators=(",", ":"),
    )

    try:
        with transaction(connection):
            website = connection.execute(
                """
                SELECT 1
                FROM websites
                WHERE id = ?
                """,
                (check.website_id,),
            ).fetchone()

            if website is None:
                raise WebsiteCheckStorageError(f"Website not found: {check.website_id}")

            cursor = connection.execute(
                """
                INSERT INTO website_checks (
                    website_id,
                    requested_url,
                    final_url,
                    dns_status,
                    dns_addresses,
                    tls_status,
                    tls_expires_at,
                    https_status_code,
                    http_status_code,
                    redirect_count,
                    response_time_ms,
                    content_type,
                    canonical_url,
                    soft_404,
                    parked_or_for_sale,
                    identity_score,
                    outcome,
                    error_message
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    check.website_id,
                    check.requested_url.strip(),
                    (None if check.final_url is None else check.final_url.strip()),
                    check.dns_status.value,
                    addresses_json,
                    check.tls_status.value,
                    (
                        None
                        if check.tls_expires_at is None
                        else check.tls_expires_at.strip()
                    ),
                    check.https_status_code,
                    check.http_status_code,
                    check.redirect_count,
                    check.response_time_ms,
                    (
                        None
                        if check.content_type is None
                        else check.content_type.strip()
                    ),
                    (
                        None
                        if check.canonical_url is None
                        else check.canonical_url.strip()
                    ),
                    int(check.soft_404),
                    int(check.parked_or_for_sale),
                    check.identity_score,
                    check.outcome.value,
                    (
                        None
                        if check.error_message is None
                        else check.error_message.strip()
                    ),
                ),
            )

            if cursor.lastrowid is None:
                raise WebsiteCheckStorageError(
                    "Website check insert returned no row ID"
                )

            return int(cursor.lastrowid)

    except sqlite3.Error as exc:
        raise WebsiteCheckStorageError(
            f"Website check database operation failed: {exc}"
        ) from exc


def list_website_checks(
    connection: sqlite3.Connection,
    *,
    website_id: int | None = None,
) -> tuple[WebsiteCheckRecord, ...]:
    if website_id is not None and website_id < 1:
        raise WebsiteCheckStorageError("website_id must be a positive integer")

    query = """
        SELECT
            id,
            website_id,
            requested_url,
            final_url,
            dns_status,
            dns_addresses,
            tls_status,
            tls_expires_at,
            https_status_code,
            http_status_code,
            redirect_count,
            response_time_ms,
            content_type,
            canonical_url,
            soft_404,
            parked_or_for_sale,
            identity_score,
            outcome,
            error_message,
            checked_at
        FROM website_checks
    """

    parameters: tuple[object, ...] = ()

    if website_id is not None:
        query += " WHERE website_id = ?"
        parameters = (website_id,)

    query += " ORDER BY checked_at DESC, id DESC"

    try:
        rows = connection.execute(
            query,
            parameters,
        ).fetchall()
    except sqlite3.Error as exc:
        raise WebsiteCheckStorageError(f"Website check listing failed: {exc}") from exc

    records: list[WebsiteCheckRecord] = []

    for row in rows:
        try:
            decoded = json.loads(str(row["dns_addresses"]))
        except json.JSONDecodeError as exc:
            raise WebsiteCheckStorageError(
                "Stored dns_addresses value is invalid JSON"
            ) from exc

        if not isinstance(decoded, list) or not all(
            isinstance(item, str) for item in decoded
        ):
            raise WebsiteCheckStorageError("Stored dns_addresses value is invalid")

        records.append(
            WebsiteCheckRecord(
                check_id=int(row["id"]),
                website_id=int(row["website_id"]),
                requested_url=str(row["requested_url"]),
                final_url=(None if row["final_url"] is None else str(row["final_url"])),
                dns_status=DNSStatus(str(row["dns_status"])),
                dns_addresses=tuple(decoded),
                tls_status=TLSStatus(str(row["tls_status"])),
                tls_expires_at=(
                    None
                    if row["tls_expires_at"] is None
                    else str(row["tls_expires_at"])
                ),
                https_status_code=(
                    None
                    if row["https_status_code"] is None
                    else int(row["https_status_code"])
                ),
                http_status_code=(
                    None
                    if row["http_status_code"] is None
                    else int(row["http_status_code"])
                ),
                redirect_count=int(row["redirect_count"]),
                response_time_ms=(
                    None
                    if row["response_time_ms"] is None
                    else int(row["response_time_ms"])
                ),
                content_type=(
                    None if row["content_type"] is None else str(row["content_type"])
                ),
                canonical_url=(
                    None if row["canonical_url"] is None else str(row["canonical_url"])
                ),
                soft_404=bool(row["soft_404"]),
                parked_or_for_sale=bool(row["parked_or_for_sale"]),
                identity_score=(
                    None
                    if row["identity_score"] is None
                    else float(row["identity_score"])
                ),
                outcome=WebsiteCheckOutcome(str(row["outcome"])),
                error_message=(
                    None if row["error_message"] is None else str(row["error_message"])
                ),
                checked_at=str(row["checked_at"]),
            )
        )

    return tuple(records)
