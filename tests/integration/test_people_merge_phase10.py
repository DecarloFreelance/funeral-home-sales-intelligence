from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from canada_funeral_intel.people.cli import run_people_merge, run_people_rollback
from canada_funeral_intel.people.merge import merge_people, rollback_person_merge
from canada_funeral_intel.people.models import (
    PersonMergeDecision,
    PersonResolutionError,
)
from canada_funeral_intel.people.resolution import list_people, show_person
from canada_funeral_intel.storage.database import database_session
from canada_funeral_intel.storage.migrations import apply_pending_migrations

MIGRATIONS = Path(__file__).resolve().parents[2] / "database" / "migrations"


def _fixture(
    connection, *, branch: bool = False, conflict: bool = False
) -> tuple[int, int, int, int, int]:
    entity_type = "branch" if branch else "organization"
    entity = connection.execute(
        "INSERT INTO entities (entity_type, canonical_name) VALUES (?, 'Home')",
        (entity_type,),
    )
    entity_id = int(entity.lastrowid)
    website = connection.execute(
        "INSERT INTO websites (entity_id, url, normalized_url, domain, discovery_method, status, website_kind) VALUES (?, 'https://home.example/', 'https://home.example/', 'home.example', 'test', 'review', 'official')",
        (entity_id,),
    )
    website_id = int(website.lastrowid)
    page = connection.execute(
        "INSERT INTO website_pages (website_id, url, normalized_url, path, page_kind, status_code, content_type) VALUES (?, 'https://home.example/team', 'https://home.example/team', '/team', 'team', 200, 'text/html')",
        (website_id,),
    )
    page_id = int(page.lastrowid)
    connection.execute(
        "INSERT INTO website_review_queue (website_id) VALUES (?)", (website_id,)
    )
    ids = []
    for number, person_name in ((1, "Alice Smith"), (2, "Alice Smith")):
        person = connection.execute(
            "INSERT INTO people (canonical_name, normalized_name) VALUES (?, ?)",
            (person_name, person_name.casefold()),
        )
        person_id = int(person.lastrowid)
        observation_hash = hashlib.sha256(f"obs-{number}".encode()).hexdigest()
        observation = connection.execute(
            """
            INSERT INTO website_page_person_observations
            (website_page_id, website_id, entity_id, observed_name, normalized_name,
             role_title, normalized_role, email, normalized_email, phone, normalized_phone,
             confidence, extraction_method, extractor_version, evidence_snippet, source_url, content_hash)
            VALUES (?, ?, ?, ?, ?, 'Director', 'director', ?, ?, '403-555-0100', '+14035550100',
                    .9, 'structured_role_block', 'phase8-test', 'Alice evidence',
                    'https://home.example/team', ?)
            """,
            (
                page_id,
                website_id,
                entity_id,
                person_name,
                person_name.casefold(),
                "one@example.ca"
                if not conflict or number == 1
                else "different@example.ca",
                "one@example.ca"
                if not conflict or number == 1
                else "different@example.ca",
                observation_hash,
            ),
        )
        observation_id = int(observation.lastrowid)
        connection.execute(
            "INSERT INTO person_observation_review_queue (observation_id, status, reviewer_note, reviewed_at) VALUES (?, 'accepted', 'reviewed', '2026-01-01T00:00:00Z')",
            (observation_id,),
        )
        connection.execute(
            "INSERT INTO person_evidence (person_id, observation_id, review_decision) VALUES (?, ?, 'accepted')",
            (person_id, observation_id),
        )
        connection.execute(
            "INSERT INTO person_affiliations (person_id, entity_id, observed_role, normalized_role, branch_context, confidence, source_observation_id) VALUES (?, ?, 'Director', 'director', '', .9, ?)",
            (person_id, entity_id, observation_id),
        )
        connection.execute(
            "INSERT INTO person_contact_points (person_id, contact_type, observed_value, normalized_value, confidence, source_observation_id) VALUES (?, 'email', ?, ?, .9, ?)",
            (
                person_id,
                "one@example.ca"
                if not conflict or number == 1
                else "different@example.ca",
                "one@example.ca"
                if not conflict or number == 1
                else "different@example.ca",
                observation_id,
            ),
        )
        connection.execute(
            "INSERT INTO person_contact_points (person_id, contact_type, observed_value, normalized_value, confidence, source_observation_id) VALUES (?, 'phone', '403-555-0100', '+14035550100', .9, ?)",
            (person_id, observation_id),
        )
        ids.append(person_id)
    return ids[0], ids[1], entity_id, website_id, page_id


def test_merge_and_rollback_preserve_history_evidence_and_website_state(
    tmp_path: Path,
) -> None:
    with database_session(tmp_path / "merge.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        survivor, absorbed, _entity_id, website_id, _ = _fixture(connection)
        connection.commit()
        before_observations = [
            tuple(row)
            for row in connection.execute(
                "SELECT * FROM website_page_person_observations ORDER BY id"
            )
        ]
        before_review = [
            tuple(row)
            for row in connection.execute(
                "SELECT * FROM person_observation_review_queue ORDER BY id"
            )
        ]
        before_website = tuple(
            connection.execute(
                "SELECT status, website_kind, is_primary FROM websites WHERE id = ?",
                (website_id,),
            ).fetchone()
        )
        result = merge_people(
            connection,
            PersonMergeDecision(
                survivor, absorbed, "test", "explicit compatible identity"
            ),
        )
        assert result.absorbed_person_id == absorbed
        assert result.affiliations_moved == 0 and result.affiliations_deduplicated == 1
        assert result.contacts_moved == 0 and result.contacts_deduplicated == 2
        assert result.evidence_moved == 1
        assert [p.person_id for p in list_people(connection)] == [survivor]
        assert show_person(connection, absorbed)["status"] == "merged"
        assert (
            connection.execute(
                "SELECT count(*) FROM person_merge_history WHERE id = ?",
                (result.merge_history_id,),
            ).fetchone()[0]
            == 1
        )
        rollback = rollback_person_merge(
            connection, result.merge_history_id, actor="test", reason="rollback test"
        )
        assert (
            rollback.restored_affiliations == 1
            and rollback.restored_contacts == 2
            and rollback.restored_evidence == 1
        )
        assert {p.person_id for p in list_people(connection)} == {survivor, absorbed}
        assert (
            connection.execute(
                "SELECT status FROM people WHERE id = ?", (absorbed,)
            ).fetchone()[0]
            == "active"
        )
        assert [
            tuple(row)
            for row in connection.execute(
                "SELECT * FROM website_page_person_observations ORDER BY id"
            )
        ] == before_observations
        assert [
            tuple(row)
            for row in connection.execute(
                "SELECT * FROM person_observation_review_queue ORDER BY id"
            )
        ] == before_review
        assert (
            tuple(
                connection.execute(
                    "SELECT status, website_kind, is_primary FROM websites WHERE id = ?",
                    (website_id,),
                ).fetchone()
            )
            == before_website
        )
        assert (
            connection.execute("SELECT count(*) FROM entity_review_queue").fetchone()[0]
            == 0
        )
        with pytest.raises(PersonResolutionError):
            rollback_person_merge(
                connection,
                result.merge_history_id,
                actor="test",
                reason="second rollback",
            )


def test_merge_rejects_conflicts_self_missing_and_cross_branch(tmp_path: Path) -> None:
    with database_session(tmp_path / "guards.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        survivor, absorbed, _, _, _ = _fixture(connection, conflict=True)
        connection.commit()
        with pytest.raises(PersonResolutionError):
            merge_people(
                connection, PersonMergeDecision(survivor, absorbed, "test", "conflict")
            )
        assert (
            connection.execute("SELECT count(*) FROM person_merge_history").fetchone()[
                0
            ]
            == 0
        )
        with pytest.raises(PersonResolutionError):
            merge_people(
                connection, PersonMergeDecision(survivor, survivor, "test", "self")
            )
        with pytest.raises(PersonResolutionError):
            merge_people(
                connection, PersonMergeDecision(survivor, 99999, "test", "missing")
            )

        branch_a, branch_b, _, _, _ = _fixture(connection, branch=True)
        other_branch = int(
            connection.execute(
                "INSERT INTO entities (entity_type, canonical_name) VALUES ('branch', 'Other branch')"
            ).lastrowid
        )
        connection.execute(
            "UPDATE person_affiliations SET entity_id = ? WHERE person_id = ?",
            (other_branch, branch_b),
        )
        connection.commit()
        with pytest.raises(PersonResolutionError):
            merge_people(
                connection,
                PersonMergeDecision(branch_a, branch_b, "test", "cross branch"),
            )


def test_deduplicated_children_are_retained_and_cli_payloads_are_auditable(
    tmp_path: Path,
) -> None:
    with database_session(tmp_path / "dedupe.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        survivor, absorbed, _, _, _ = _fixture(connection)
        connection.execute(
            "UPDATE person_contact_points SET normalized_value = 'one@example.ca' WHERE person_id = ? AND contact_type = 'email'",
            (absorbed,),
        )
        connection.execute(
            "UPDATE person_affiliations SET source_observation_id = (SELECT source_observation_id FROM person_affiliations WHERE person_id = ? LIMIT 1) WHERE person_id = ?",
            (survivor, absorbed),
        )
        connection.commit()
        payload = run_people_merge(
            connection,
            survivor_person_id=survivor,
            absorbed_person_id=absorbed,
            reason="dedupe",
        )
        assert {
            "merge_id",
            "survivor_person_id",
            "absorbed_person_id",
            "created_at",
        } <= payload.keys()
        assert (
            connection.execute(
                "SELECT count(*) FROM person_affiliations WHERE person_id = ? AND active = 0",
                (absorbed,),
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM person_contact_points WHERE person_id = ? AND active = 0",
                (absorbed,),
            ).fetchone()[0]
            == 2
        )
        rollback = run_people_rollback(
            connection, merge_id=payload["merge_id"], reason="dedupe rollback"
        )
        assert {"merge_id", "restored_person_id", "rolled_back_at"} <= rollback.keys()
