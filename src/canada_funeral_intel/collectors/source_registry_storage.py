from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from canada_funeral_intel.collectors.source_registry import SourceDefinition


@dataclass(frozen=True, slots=True)
class SeedResult:
    inserted: int
    updated: int
    unchanged: int

    @property
    def total(self) -> int:
        return self.inserted + self.updated + self.unchanged


_FIELDS = (
    "source_type",
    "source_url",
    "publisher",
    "jurisdiction",
    "license_name",
    "license_url",
    "notes",
    "is_active",
    "source_format",
    "trust_level",
    "refresh_interval_days",
    "coverage",
    "licensing_notes",
)


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _database_values(definition: SourceDefinition) -> dict[str, object]:
    record = definition.as_record()
    return {
        "name": record["name"],
        "source_type": record["source_type"],
        "source_url": record["source_url"],
        "publisher": record["publisher"],
        "jurisdiction": record["jurisdiction"],
        "license_name": record["license_name"],
        "license_url": record["license_url"],
        "notes": record["notes"],
        "is_active": 1 if record["enabled"] else 0,
        "source_format": record["source_format"],
        "trust_level": record["trust_level"],
        "refresh_interval_days": record["refresh_interval_days"],
        "coverage": record["coverage"],
        "licensing_notes": record["licensing_notes"],
    }


def seed_source_registry(
    connection: sqlite3.Connection,
    definitions: tuple[SourceDefinition, ...],
) -> SeedResult:
    inserted = 0
    updated = 0
    unchanged = 0

    ordered = sorted(definitions, key=lambda item: item.name.casefold())

    for definition in ordered:
        definition.validate()
        values = _database_values(definition)

        current = connection.execute(
            """
            SELECT
                name,
                source_type,
                source_url,
                publisher,
                jurisdiction,
                license_name,
                license_url,
                notes,
                is_active,
                source_format,
                trust_level,
                refresh_interval_days,
                coverage,
                licensing_notes
            FROM source_datasets
            WHERE name = ?
            """,
            (definition.name,),
        ).fetchone()

        if current is None:
            connection.execute(
                """
                INSERT INTO source_datasets (
                    name,
                    source_type,
                    source_url,
                    publisher,
                    jurisdiction,
                    license_name,
                    license_url,
                    notes,
                    is_active,
                    source_format,
                    trust_level,
                    refresh_interval_days,
                    coverage,
                    licensing_notes
                )
                VALUES (
                    :name,
                    :source_type,
                    :source_url,
                    :publisher,
                    :jurisdiction,
                    :license_name,
                    :license_url,
                    :notes,
                    :is_active,
                    :source_format,
                    :trust_level,
                    :refresh_interval_days,
                    :coverage,
                    :licensing_notes
                )
                """,
                values,
            )
            inserted += 1
            continue

        changed = any(current[field] != values[field] for field in _FIELDS)
        if not changed:
            unchanged += 1
            continue

        update_values = dict(values)
        update_values["updated_at"] = _utc_timestamp()

        connection.execute(
            """
            UPDATE source_datasets
            SET
                source_type = :source_type,
                source_url = :source_url,
                publisher = :publisher,
                jurisdiction = :jurisdiction,
                license_name = :license_name,
                license_url = :license_url,
                notes = :notes,
                is_active = :is_active,
                source_format = :source_format,
                trust_level = :trust_level,
                refresh_interval_days = :refresh_interval_days,
                coverage = :coverage,
                licensing_notes = :licensing_notes,
                updated_at = :updated_at
            WHERE name = :name
            """,
            update_values,
        )
        updated += 1

    return SeedResult(
        inserted=inserted,
        updated=updated,
        unchanged=unchanged,
    )
