from __future__ import annotations

import json
import sqlite3

from canada_funeral_intel.deduplication.entity_materialization import (
    EntityMaterializationError,
    materialize_source_record_entities,
)


class EntityCommandError(RuntimeError):
    """Raised when an entity CLI command cannot complete safely."""


def run_entity_materialize(
    connection: sqlite3.Connection,
) -> dict[str, object]:
    try:
        result = materialize_source_record_entities(connection)
    except EntityMaterializationError as exc:
        raise EntityCommandError(str(exc)) from exc

    return {
        "source_records_seen": result.source_records_seen,
        "entities_inserted": result.entities_inserted,
        "memberships_inserted": result.memberships_inserted,
        "records_unchanged": result.records_unchanged,
    }


def print_entity_payload(
    payload: object,
) -> None:
    print(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
        )
    )
