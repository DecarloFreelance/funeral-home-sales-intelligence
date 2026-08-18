from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PUBLIC_DIRECTORY_VERSION = "public-directory-v2"

_PUBLIC_NAME_NOISE = re.compile(
    r"\b(?:funeral|grief|office|vice|past|service|seminar|celebrant)\b.*$",
    re.IGNORECASE,
)
_PUBLIC_PAIRED_NAME = re.compile(
    r"^([A-Za-z][A-Za-z'’.-]+)\s+([A-Za-z][A-Za-z'’.-]+)\s+"
    r"([A-Za-z][A-Za-z'’.-]+)\s+\1$",
    re.IGNORECASE,
)


def _clean_public_person_name(value: str) -> str:
    paired = _PUBLIC_PAIRED_NAME.fullmatch(value.strip())
    if paired:
        first, second, surname = paired.groups()
        return f"{first} & {second} {surname}"
    cleaned = _PUBLIC_NAME_NOISE.sub("", value).strip(" ,;:-")
    return cleaned or value


def _generated_at() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _read_only_connection(database_path: Path) -> sqlite3.Connection:
    resolved = database_path.expanduser().resolve()
    connection = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def build_public_directory(database_path: Path) -> dict[str, Any]:
    """Build a curated, read-only research directory snapshot."""
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
              AND (
                  (e.canonical_name IS NOT NULL AND trim(e.canonical_name) <> '')
                  OR EXISTS (
                      SELECT 1
                      FROM normalized_values AS named_nv
                      JOIN entity_source_records AS named_esr
                        ON named_esr.source_record_id = named_nv.source_record_id
                      WHERE named_esr.entity_id = e.id
                        AND named_nv.field_name = 'business_name'
                        AND named_nv.original_value IS NOT NULL
                        AND trim(named_nv.original_value) <> ''
                  )
              )
            ORDER BY
                CASE WHEN e.canonical_name IS NULL THEN 1 ELSE 0 END,
                lower(COALESCE(e.canonical_name, '')),
                e.id
            """
        ).fetchall()
        fact_rows = connection.execute(
            """
            SELECT bf.entity_id, bf.fact_key, bf.normalized_value
            FROM business_fact_observations AS bf
            WHERE bf.normalized_value IS NOT NULL
              AND trim(bf.normalized_value) <> ''
              AND NOT EXISTS (
                  SELECT 1
                  FROM business_fact_agent_reviews AS latest
                  WHERE latest.fact_id = bf.id
                    AND latest.id = (
                        SELECT MAX(r.id)
                        FROM business_fact_agent_reviews AS r
                        WHERE r.fact_id = bf.id
                    )
                    AND latest.disposition = 'reject'
              )
            ORDER BY bf.entity_id, bf.fact_key, bf.normalized_value
            """
        ).fetchall()
        people_rows = connection.execute(
            """
            SELECT DISTINCT
                pa.entity_id, p.canonical_name, pa.observed_role,
                NULLIF(pa.branch_context, '') AS branch_context
            FROM people AS p
            JOIN person_affiliations AS pa
              ON pa.person_id = p.id AND pa.active = 1
            JOIN person_evidence AS pe
              ON pe.person_id = p.id AND pe.review_decision = 'accepted'
            WHERE p.status = 'active'
            ORDER BY pa.entity_id, lower(p.canonical_name), pa.observed_role
            """
        ).fetchall()
    finally:
        connection.close()

    facts_by_entity: dict[int, dict[str, set[str]]] = {}
    for row in fact_rows:
        entity_facts = facts_by_entity.setdefault(int(row["entity_id"]), {})
        entity_facts.setdefault(str(row["fact_key"]), set()).add(
            str(row["normalized_value"])
        )
    people_by_entity: dict[int, list[dict[str, str | None]]] = {}
    for row in people_rows:
        people_by_entity.setdefault(int(row["entity_id"]), []).append(
            {
                "name": _clean_public_person_name(str(row["canonical_name"])),
                "role": str(row["observed_role"]),
                "branch": None
                if row["branch_context"] is None
                else str(row["branch_context"]),
            }
        )

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
            "business_facts": {
                key: sorted(values)
                for key, values in sorted(
                    facts_by_entity.get(int(row["entity_id"]), {}).items()
                )
            },
            "people": people_by_entity.get(int(row["entity_id"]), []),
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
