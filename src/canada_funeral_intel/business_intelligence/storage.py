from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from canada_funeral_intel.storage.database import transaction

from .extraction import BusinessFactExtractionResult, BusinessFactPage
from .taxonomy import EXTRACTOR_VERSION


@dataclass(frozen=True, slots=True)
class FactInsertResult:
    inserted: int
    unchanged: int


def store_business_facts(
    connection: sqlite3.Connection,
    *,
    page: BusinessFactPage,
    result: BusinessFactExtractionResult,
) -> FactInsertResult:
    inserted = unchanged = 0
    with transaction(connection):
        relationship = connection.execute(
            "SELECT w.entity_id FROM website_pages AS p JOIN websites AS w ON w.id = p.website_id WHERE p.id = ? AND p.website_id = ? AND w.entity_id = ?",
            (page.website_page_id, page.website_id, page.entity_id),
        ).fetchone()
        if relationship is None:
            raise ValueError("page, website, and entity IDs are inconsistent")
        for item in result.candidates:
            existing = connection.execute(
                "SELECT id FROM business_fact_observations WHERE website_page_id = ? AND content_hash = ? AND fact_key = ? AND normalized_value = ? AND raw_value = ? AND scope_entity_id IS ?",
                (
                    page.website_page_id,
                    result.content_hash,
                    item.fact_key,
                    item.normalized_value,
                    item.raw_value,
                    item.scope_entity_id,
                ),
            ).fetchone()
            if existing is not None:
                unchanged += 1
                continue
            connection.execute(
                "INSERT INTO business_fact_observations (website_page_id, website_id, entity_id, source_url, page_kind, fact_key, value_kind, raw_value, normalized_value, scope, scope_entity_id, confidence, extraction_method, extractor_version, evidence_snippet, content_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    page.website_page_id,
                    page.website_id,
                    page.entity_id,
                    page.source_url,
                    page.page_kind,
                    item.fact_key,
                    item.value_kind,
                    item.raw_value,
                    item.normalized_value,
                    item.scope,
                    item.scope_entity_id,
                    item.confidence,
                    item.extraction_method,
                    EXTRACTOR_VERSION,
                    item.evidence_snippet,
                    result.content_hash,
                ),
            )
            inserted += 1
    return FactInsertResult(inserted, unchanged)


def list_business_facts(
    connection: sqlite3.Connection,
    *,
    entity_id: int | None = None,
    website_id: int | None = None,
    page_id: int | None = None,
    fact_key: str | None = None,
) -> list[dict[str, object]]:
    conditions, params = [], []
    for column, value in (
        ("entity_id", entity_id),
        ("website_id", website_id),
        ("website_page_id", page_id),
        ("fact_key", fact_key),
    ):
        if value is not None:
            conditions.append(f"{column} = ?")
            params.append(value)
    query = "SELECT * FROM business_fact_observations"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY entity_id, website_id, website_page_id, fact_key, normalized_value, content_hash, id"
    return [dict(row) for row in connection.execute(query, tuple(params)).fetchall()]
