from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from canada_funeral_intel.storage.database import transaction


class EntityMaterializationError(RuntimeError):
    """Raised when baseline entity materialization cannot complete safely."""


@dataclass(frozen=True, slots=True)
class EntityMaterializationResult:
    source_records_seen: int
    entities_inserted: int
    memberships_inserted: int
    records_unchanged: int


def materialize_source_record_entities(
    connection: sqlite3.Connection,
) -> EntityMaterializationResult:
    """Create one baseline branch entity per source record.

    Each source record is linked with membership_role='location'.
    The canonical name is taken from the authoritative latest
    normalized business_name value when available.

    Existing source-record memberships are treated as already
    materialized so repeated runs are idempotent.
    """
    try:
        source_rows = connection.execute(
            """
            SELECT id
            FROM source_records
            ORDER BY id
            """
        ).fetchall()

        latest_names = _load_latest_business_names(connection)

        inserted_entities = 0
        inserted_memberships = 0
        unchanged = 0

        with transaction(connection):
            for source_row in source_rows:
                source_record_id = int(source_row["id"])

                existing = connection.execute(
                    """
                    SELECT entity_id
                    FROM entity_source_records
                    WHERE source_record_id = ?
                    ORDER BY entity_id
                    LIMIT 1
                    """,
                    (source_record_id,),
                ).fetchone()

                if existing is not None:
                    unchanged += 1
                    continue

                cursor = connection.execute(
                    """
                    INSERT INTO entities (
                        entity_type,
                        canonical_name,
                        status
                    )
                    VALUES ('branch', ?, 'active')
                    """,
                    (latest_names.get(source_record_id),),
                )

                if cursor.lastrowid is None:
                    raise EntityMaterializationError("Entity insert returned no row ID")

                entity_id = int(cursor.lastrowid)

                connection.execute(
                    """
                    INSERT INTO entity_source_records (
                        entity_id,
                        source_record_id,
                        membership_role
                    )
                    VALUES (?, ?, 'location')
                    """,
                    (
                        entity_id,
                        source_record_id,
                    ),
                )

                inserted_entities += 1
                inserted_memberships += 1

    except EntityMaterializationError:
        raise
    except sqlite3.Error as exc:
        raise EntityMaterializationError(
            f"Entity materialization database operation failed: {exc}"
        ) from exc

    return EntityMaterializationResult(
        source_records_seen=len(source_rows),
        entities_inserted=inserted_entities,
        memberships_inserted=inserted_memberships,
        records_unchanged=unchanged,
    )


def _load_latest_business_names(
    connection: sqlite3.Connection,
) -> dict[int, str]:
    rows = connection.execute(
        """
        SELECT
            nv.source_record_id,
            nv.normalized_value
        FROM normalized_values AS nv
        JOIN (
            SELECT
                source_record_id,
                field_name,
                MAX(id) AS normalized_value_id
            FROM normalized_values
            WHERE field_name = 'business_name'
            GROUP BY
                source_record_id,
                field_name
        ) AS latest
          ON latest.normalized_value_id = nv.id
        WHERE nv.normalized_value IS NOT NULL
        ORDER BY nv.source_record_id
        """
    ).fetchall()

    return {int(row["source_record_id"]): str(row["normalized_value"]) for row in rows}
