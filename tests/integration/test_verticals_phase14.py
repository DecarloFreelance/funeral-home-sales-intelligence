from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from canada_funeral_intel.storage.database import database_session
from canada_funeral_intel.storage.migrations import apply_pending_migrations
from canada_funeral_intel.verticals.cli import profile_payload, profiles_payload
from canada_funeral_intel.verticals.storage import (
    assign_membership,
    list_memberships,
    seed_verticals,
)

MIGRATIONS = Path(__file__).resolve().parents[2] / "database" / "migrations"


def test_profiles_are_deterministic_and_cemetery_is_explicit() -> None:
    profiles = profiles_payload()
    assert [profile["vertical_key"] for profile in profiles] == [
        "cemetery",
        "funeral_home",
    ]
    profile = profile_payload("cemetery")
    assert profile["profile_version"] == "phase14-v1"
    assert "obituary" in profile["excluded_content"]
    assert "cemetery director" in profile["role_keywords"]
    with pytest.raises(ValueError, match="Unknown vertical"):
        profile_payload("unknown")


def test_vertical_memberships_support_multiple_verticals_and_preserve_provenance(
    tmp_path: Path,
) -> None:
    with database_session(tmp_path / "verticals.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        entity = connection.execute(
            "INSERT INTO entities (entity_type, canonical_name) VALUES ('organization', 'Multi Service Operator')"
        )
        entity_id = int(entity.lastrowid)
        connection.commit()
        assert seed_verticals(connection) == {"inserted": 2, "unchanged": 0}
        first = assign_membership(
            connection,
            entity_id=entity_id,
            vertical_key="cemetery",
            actor="fixture",
            confidence=0.8,
        )
        second = assign_membership(
            connection,
            entity_id=entity_id,
            vertical_key="cemetery",
            actor="other",
            confidence=0.2,
        )
        assert first["status"] == "inserted"
        assert second["status"] == "unchanged"
        rows = list_memberships(connection, "cemetery")
        assert rows[0]["entity_id"] == entity_id
        assert rows[0]["confidence"] == 0.8
        assert rows[0]["classification_method"] == "explicit:fixture"
        assert connection.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "DELETE FROM entity_vertical_memberships WHERE id=?",
                (first["membership_id"],),
            )


def test_invalid_entity_and_confidence_are_rejected(tmp_path: Path) -> None:
    with database_session(tmp_path / "verticals.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        with pytest.raises(ValueError, match="Entity not found"):
            assign_membership(
                connection, entity_id=999, vertical_key="cemetery", actor="fixture"
            )
        entity = connection.execute(
            "INSERT INTO entities (entity_type, canonical_name) VALUES ('branch', 'Branch')"
        )
        connection.commit()
        with pytest.raises(ValueError, match="actor and confidence"):
            assign_membership(
                connection,
                entity_id=int(entity.lastrowid),
                vertical_key="cemetery",
                actor="",
                confidence=1.1,
            )
