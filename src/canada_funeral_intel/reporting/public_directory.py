from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PUBLIC_DIRECTORY_VERSION = "public-directory-v1"


def _generated_at() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _read_only_connection(database_path: Path) -> sqlite3.Connection:
    resolved = database_path.expanduser().resolve()
    connection = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def build_public_directory(database_path: Path) -> dict[str, Any]:
    """Build a deliberately narrow, read-only public directory snapshot."""
    connection = _read_only_connection(database_path)
    try:
        rows = connection.execute(
            """
            SELECT
                e.id AS entity_id,
                e.entity_type,
                COALESCE(
                    (
                        SELECT nv.original_value
                        FROM normalized_values AS nv
                        JOIN entity_source_records AS esr
                          ON esr.source_record_id = nv.source_record_id
                        WHERE esr.entity_id = e.id
                          AND nv.field_name = 'business_name'
                          AND nv.original_value IS NOT NULL
                          AND trim(nv.original_value) <> ''
                          AND length(nv.original_value) <= 200
                        ORDER BY nv.source_record_id DESC, nv.id DESC
                        LIMIT 1
                    ),
                    e.canonical_name
                ) AS canonical_name,
                (
                    SELECT nv.normalized_value
                    FROM normalized_values AS nv
                    JOIN entity_source_records AS esr
                      ON esr.source_record_id = nv.source_record_id
                    WHERE esr.entity_id = e.id
                      AND nv.field_name = 'city'
                      AND nv.normalized_value IS NOT NULL
                      AND trim(nv.normalized_value) <> ''
                    ORDER BY nv.source_record_id DESC, nv.id DESC
                    LIMIT 1
                ) AS city,
                (
                    SELECT nv.normalized_value
                    FROM normalized_values AS nv
                    JOIN entity_source_records AS esr
                      ON esr.source_record_id = nv.source_record_id
                    WHERE esr.entity_id = e.id
                      AND nv.field_name = 'province'
                      AND nv.normalized_value IS NOT NULL
                      AND trim(nv.normalized_value) <> ''
                    ORDER BY nv.source_record_id DESC, nv.id DESC
                    LIMIT 1
                ) AS province,
                (
                    SELECT group_concat(DISTINCT sd.name)
                    FROM source_datasets AS sd
                    JOIN source_records AS sr ON sr.source_dataset_id = sd.id
                    JOIN entity_source_records AS esr
                      ON esr.source_record_id = sr.id
                    WHERE esr.entity_id = e.id
                ) AS source_names,
                (
                    SELECT w.url
                    FROM websites AS w
                    WHERE w.entity_id = e.id
                    ORDER BY
                        CASE w.status
                            WHEN 'selected' THEN 0
                            WHEN 'review' THEN 1
                            WHEN 'candidate' THEN 2
                            WHEN 'rejected' THEN 3
                            ELSE 4
                        END,
                        w.is_primary DESC,
                        w.confidence DESC,
                        w.id
                    LIMIT 1
                ) AS website_url,
                (
                    SELECT w.status
                    FROM websites AS w
                    WHERE w.entity_id = e.id
                    ORDER BY
                        CASE w.status
                            WHEN 'selected' THEN 0
                            WHEN 'review' THEN 1
                            WHEN 'candidate' THEN 2
                            WHEN 'rejected' THEN 3
                            ELSE 4
                        END,
                        w.is_primary DESC,
                        w.confidence DESC,
                        w.id
                    LIMIT 1
                ) AS website_status
            FROM entities AS e
            WHERE e.status = 'active'
            ORDER BY
                CASE WHEN e.canonical_name IS NULL THEN 1 ELSE 0 END,
                lower(COALESCE(e.canonical_name, '')),
                e.id
            """
        ).fetchall()
    finally:
        connection.close()

    records = [
        {
            "entity_id": int(row["entity_id"]),
            "entity_type": str(row["entity_type"]),
            "name": None
            if row["canonical_name"] is None
            else str(row["canonical_name"]),
            "city": None if row["city"] is None else str(row["city"]),
            "province": None if row["province"] is None else str(row["province"]),
            "source_names": (
                []
                if row["source_names"] is None
                else sorted(str(row["source_names"]).split(","))
            ),
            "website_url": (
                None if row["website_url"] is None else str(row["website_url"])
            ),
            "website_status": (
                None if row["website_status"] is None else str(row["website_status"])
            ),
        }
        for row in rows
    ]
    return {
        "directory_version": PUBLIC_DIRECTORY_VERSION,
        "generated_at": _generated_at(),
        "record_count": len(records),
        "records": records,
    }


def write_public_directory(database_path: Path, output_path: Path) -> dict[str, Any]:
    payload = build_public_directory(database_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload
