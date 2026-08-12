from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from canada_funeral_intel.people.cli import run_people_review_list
from canada_funeral_intel.people.models import PersonResolutionError, PersonReviewStatus
from canada_funeral_intel.people.resolution import (
    apply_person_review_decision,
    list_person_review_queue,
    populate_person_review_queue,
    resolve_accepted_observation,
)
from canada_funeral_intel.storage.database import database_session
from canada_funeral_intel.storage.migrations import apply_pending_migrations

MIGRATIONS = Path(__file__).resolve().parents[2] / "database" / "migrations"


def _observation(connection, *, entity_id: int, website_id: int, page_id: int, name: str, email: str = "", phone: str = "", role: str = "Funeral Director", number: int = 1) -> int:
    digest = hashlib.sha256(f"{entity_id}-{number}-{name}-{email}-{phone}".encode()).hexdigest()
    cursor = connection.execute(
        """
        INSERT INTO website_page_person_observations
        (website_page_id, website_id, entity_id, observed_name, normalized_name,
         role_title, normalized_role, email, normalized_email, phone, normalized_phone,
         branch_context, confidence, extraction_method, extractor_version,
         evidence_snippet, source_url, content_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.9,
                'structured_role_block', 'phase8-test', ?, ?, ?)
        """,
        (page_id, website_id, entity_id, name, name.casefold(), role, role.casefold(),
         email or None, email.casefold(), phone or None, phone, None,
         f"{name} — {role}", f"https://example{entity_id}.ca/team", digest),
    )
    return int(cursor.lastrowid)


def _database(connection):
    entities = []
    for name in ("Home A", "Home B"):
        cursor = connection.execute("INSERT INTO entities (entity_type, canonical_name) VALUES ('organization', ?)", (name,))
        entities.append(int(cursor.lastrowid))
    websites = []
    pages = []
    for entity_id in entities:
        website = connection.execute("INSERT INTO websites (entity_id, url, normalized_url, domain, discovery_method, status) VALUES (?, ?, ?, ?, 'test', 'review')", (entity_id, f"https://example{entity_id}.ca/", f"https://example{entity_id}.ca/", f"example{entity_id}.ca"))
        website_id = int(website.lastrowid)
        page = connection.execute("INSERT INTO website_pages (website_id, url, normalized_url, path, page_kind, status_code, content_type) VALUES (?, ?, ?, '/team', 'team', 200, 'text/html')", (website_id, f"https://example{entity_id}.ca/team", f"https://example{entity_id}.ca/team"))
        websites.append(website_id)
        pages.append(int(page.lastrowid))
    connection.execute("INSERT INTO website_review_queue (website_id) VALUES (?)", (websites[0],))
    return entities, websites, pages


def test_person_review_resolution_is_conservative_and_provenance_rich(tmp_path: Path) -> None:
    with database_session(tmp_path / "people.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        entities, websites, pages = _database(connection)
        first = _observation(connection, entity_id=entities[0], website_id=websites[0], page_id=pages[0], name="Alice Smith", email="alice@example.ca", phone="403-555-0100")
        repeated = _observation(connection, entity_id=entities[0], website_id=websites[0], page_id=pages[0], name="Alice Smith", email="ALICE@example.ca", phone="403-555-0100", number=2)
        other_branch = _observation(connection, entity_id=entities[1], website_id=websites[1], page_id=pages[1], name="Alice Smith", email="", number=3)
        conflicting = _observation(connection, entity_id=entities[0], website_id=websites[0], page_id=pages[0], name="Alice Smith", email="other@example.ca", number=4)
        name_only = _observation(connection, entity_id=entities[0], website_id=websites[0], page_id=pages[0], name="Bob Jones", role="Owner", number=5)
        rejected = _observation(connection, entity_id=entities[0], website_id=websites[0], page_id=pages[0], name="Nope", number=6)
        connection.commit()

        assert populate_person_review_queue(connection) == (6, 0)
        assert populate_person_review_queue(connection) == (0, 6)
        queues = list_person_review_queue(connection)
        assert run_people_review_list(connection, PersonReviewStatus.PENDING) == run_people_review_list(connection, PersonReviewStatus.PENDING)
        assert [row["observation_id"] for row in queues] == [first, repeated, other_branch, conflicting, name_only, rejected]

        for row in queues[:-1]:
            apply_person_review_decision(connection, queue_id=int(row["queue_id"]), status=PersonReviewStatus.ACCEPTED)
        apply_person_review_decision(connection, queue_id=int(queues[-1]["queue_id"]), status=PersonReviewStatus.REJECTED)
        with pytest.raises(PersonResolutionError):
            apply_person_review_decision(connection, queue_id=int(queues[-1]["queue_id"]), status=PersonReviewStatus.ACCEPTED)

        person = resolve_accepted_observation(connection, first)
        assert resolve_accepted_observation(connection, repeated) == person
        assert resolve_accepted_observation(connection, other_branch) != person
        assert resolve_accepted_observation(connection, conflicting) != person
        assert resolve_accepted_observation(connection, name_only) != person
        with pytest.raises(PersonResolutionError):
            resolve_accepted_observation(connection, rejected)

        source = connection.execute("SELECT * FROM website_page_person_observations WHERE id = ?", (first,)).fetchone()
        evidence = connection.execute("SELECT observation_id FROM person_evidence WHERE observation_id = ?", (first,)).fetchone()
        assert source["source_url"] == f"https://example{entities[0]}.ca/team"
        assert evidence["observation_id"] == first
        website = connection.execute("SELECT status, website_kind, is_primary FROM websites WHERE id = ?", (websites[0],)).fetchone()
        queue = connection.execute("SELECT status FROM website_review_queue WHERE website_id = ?", (websites[0],)).fetchone()
        assert tuple(website) == ("review", "candidate", 0)
        assert queue["status"] == "pending"
