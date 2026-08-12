from __future__ import annotations

import sqlite3

from canada_funeral_intel.storage.database import transaction

from .registry import get_profile, list_profiles


def seed_verticals(connection: sqlite3.Connection) -> dict[str, int]:
    inserted = unchanged = 0
    with transaction(connection):
        for profile in list_profiles():
            existing = connection.execute("SELECT id FROM business_verticals WHERE vertical_key=?", (profile.key,)).fetchone()
            if existing:
                unchanged += 1
            else:
                connection.execute("INSERT INTO business_verticals (vertical_key, display_name, profile_version) VALUES (?, ?, ?)", (profile.key, profile.display_name, profile.profile_version))
                inserted += 1
    return {"inserted": inserted, "unchanged": unchanged}


def assign_membership(connection: sqlite3.Connection, *, entity_id: int, vertical_key: str, actor: str, confidence: float = 1.0, source_record_id: int | None = None) -> dict[str, object]:
    profile = get_profile(vertical_key)
    actor = actor.strip()
    if not actor or not 0.0 <= confidence <= 1.0:
        raise ValueError("actor and confidence are required")
    with transaction(connection):
        if connection.execute("SELECT 1 FROM entities WHERE id=?", (entity_id,)).fetchone() is None:
            raise ValueError(f"Entity not found: {entity_id}")
        if connection.execute("SELECT id FROM business_verticals WHERE vertical_key=?", (vertical_key,)).fetchone() is None:
            connection.execute("INSERT INTO business_verticals (vertical_key, display_name, profile_version) VALUES (?, ?, ?)", (profile.key, profile.display_name, profile.profile_version))
        vertical_id = int(connection.execute("SELECT id FROM business_verticals WHERE vertical_key=?", (vertical_key,)).fetchone()[0])
        existing = connection.execute("SELECT * FROM entity_vertical_memberships WHERE entity_id=? AND vertical_id=?", (entity_id, vertical_id)).fetchone()
        if existing:
            return {"membership_id": int(existing["id"]), "entity_id": entity_id, "vertical": vertical_key, "status": "unchanged"}
        row = connection.execute("INSERT INTO entity_vertical_memberships (entity_id, vertical_id, confidence, classification_method, classification_version, source_record_id) VALUES (?, ?, ?, ?, ?, ?) RETURNING id", (entity_id, vertical_id, confidence, f"explicit:{actor}", profile.profile_version, source_record_id)).fetchone()
    return {"membership_id": int(row["id"]), "entity_id": entity_id, "vertical": vertical_key, "status": "inserted"}


def list_memberships(connection: sqlite3.Connection, vertical_key: str) -> list[dict[str, object]]:
    get_profile(vertical_key)
    rows = connection.execute("SELECT m.id AS membership_id, m.entity_id, v.vertical_key, v.display_name, m.confidence, m.classification_method, m.classification_version, m.source_record_id, m.created_at FROM entity_vertical_memberships m JOIN business_verticals v ON v.id=m.vertical_id WHERE v.vertical_key=? ORDER BY m.entity_id, m.id", (vertical_key,)).fetchall()
    return [dict(row) for row in rows]
