from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from canada_funeral_intel.extraction.person_analysis import (
    EXTRACTOR_VERSION,
    PersonObservationCandidate,
)
from canada_funeral_intel.storage.database import transaction


class PersonObservationStorageError(RuntimeError):
    """Raised when person observation persistence cannot complete safely."""


@dataclass(frozen=True, slots=True)
class ObservationInsertResult:
    observation_id: int
    inserted: bool


def insert_page_person_observation(
    connection: sqlite3.Connection,
    *,
    website_page_id: int,
    website_id: int,
    entity_id: int,
    source_url: str,
    content_hash: str,
    candidate: PersonObservationCandidate,
) -> ObservationInsertResult:
    if website_page_id < 1 or website_id < 1 or entity_id < 1:
        raise PersonObservationStorageError("observation IDs must be positive")
    try:
        with transaction(connection):
            relationship = connection.execute(
                """
                SELECT 1
                FROM website_pages AS wp
                JOIN websites AS w ON w.id = wp.website_id
                WHERE wp.id = ?
                  AND wp.website_id = ?
                  AND w.entity_id = ?
                """,
                (website_page_id, website_id, entity_id),
            ).fetchone()
            if relationship is None:
                raise PersonObservationStorageError(
                    "page, website, and entity IDs are inconsistent"
                )

            existing = connection.execute(
                """
                SELECT id
                FROM website_page_person_observations
                WHERE website_page_id = ?
                  AND content_hash = ?
                  AND normalized_name = ?
                  AND normalized_role = ?
                  AND normalized_email = ?
                  AND normalized_phone = ?
                """,
                (
                    website_page_id,
                    content_hash,
                    candidate.normalized_name,
                    candidate.normalized_role,
                    candidate.normalized_email or "",
                    candidate.normalized_phone or "",
                ),
            ).fetchone()
            if existing is not None:
                return ObservationInsertResult(int(existing["id"]), False)

            cursor = connection.execute(
                """
                INSERT INTO website_page_person_observations (
                    website_page_id,
                    website_id,
                    entity_id,
                    observed_name,
                    normalized_name,
                    role_title,
                    normalized_role,
                    email,
                    normalized_email,
                    phone,
                    normalized_phone,
                    branch_context,
                    confidence,
                    extraction_method,
                    extractor_version,
                    evidence_snippet,
                    source_url,
                    content_hash
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    website_page_id,
                    website_id,
                    entity_id,
                    candidate.observed_name,
                    candidate.normalized_name,
                    candidate.role_title,
                    candidate.normalized_role,
                    candidate.email,
                    candidate.normalized_email or "",
                    candidate.phone,
                    candidate.normalized_phone or "",
                    candidate.branch_context,
                    candidate.confidence,
                    candidate.extraction_method.value,
                    EXTRACTOR_VERSION,
                    candidate.evidence_snippet,
                    source_url,
                    content_hash,
                ),
            )
            if cursor.lastrowid is None:
                raise PersonObservationStorageError(
                    "person observation insert returned no row ID"
                )
            return ObservationInsertResult(int(cursor.lastrowid), True)
    except sqlite3.Error as exc:
        raise PersonObservationStorageError(
            f"person observation persistence failed: {exc}"
        ) from exc


def list_page_person_observations(
    connection: sqlite3.Connection,
    *,
    website_id: int | None = None,
    page_id: int | None = None,
    entity_id: int | None = None,
) -> tuple[dict[str, object], ...]:
    filters: list[str] = []
    parameters: list[object] = []
    for column, value in (
        ("website_id", website_id),
        ("website_page_id", page_id),
        ("entity_id", entity_id),
    ):
        if value is not None:
            if value < 1:
                raise PersonObservationStorageError(f"{column} must be positive")
            filters.append(f"{column} = ?")
            parameters.append(value)

    query = """
        SELECT
            id,
            website_page_id,
            website_id,
            entity_id,
            observed_name,
            normalized_name,
            role_title,
            normalized_role,
            email,
            normalized_email,
            phone,
            normalized_phone,
            branch_context,
            confidence,
            extraction_method,
            extractor_version,
            evidence_snippet,
            source_url,
            content_hash,
            created_at,
            updated_at
        FROM website_page_person_observations
    """
    if filters:
        query += " WHERE " + " AND ".join(filters)
    query += " ORDER BY website_id, website_page_id, normalized_name, id"

    try:
        rows = connection.execute(query, tuple(parameters)).fetchall()
    except sqlite3.Error as exc:
        raise PersonObservationStorageError(
            f"person observation listing failed: {exc}"
        ) from exc

    return tuple(
        {
            "observation_id": int(row["id"]),
            "website_page_id": int(row["website_page_id"]),
            "website_id": int(row["website_id"]),
            "entity_id": int(row["entity_id"]),
            "observed_name": str(row["observed_name"]),
            "normalized_name": str(row["normalized_name"]),
            "role_title": str(row["role_title"]),
            "normalized_role": str(row["normalized_role"]),
            "email": None if row["email"] is None else str(row["email"]),
            "normalized_email": str(row["normalized_email"]),
            "phone": None if row["phone"] is None else str(row["phone"]),
            "normalized_phone": str(row["normalized_phone"]),
            "branch_context": (
                None
                if row["branch_context"] is None
                else str(row["branch_context"])
            ),
            "confidence": float(row["confidence"]),
            "extraction_method": str(row["extraction_method"]),
            "extractor_version": str(row["extractor_version"]),
            "evidence_snippet": str(row["evidence_snippet"]),
            "source_url": str(row["source_url"]),
            "content_hash": str(row["content_hash"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }
        for row in rows
    )
