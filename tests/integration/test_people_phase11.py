from __future__ import annotations

from pathlib import Path

import pytest

from canada_funeral_intel.people.audit import (
    audit_people_list,
    audit_person,
    export_people_csv,
)
from canada_funeral_intel.people.merge import merge_people, rollback_person_merge
from canada_funeral_intel.people.models import (
    PersonMergeDecision,
    PersonResolutionError,
)
from canada_funeral_intel.storage.database import database_session
from canada_funeral_intel.storage.migrations import apply_pending_migrations
from tests.integration.test_people_merge_phase10 import _fixture

MIGRATIONS = Path(__file__).resolve().parents[2] / "database" / "migrations"


def test_person_audit_contains_end_to_end_provenance_and_is_read_only(tmp_path: Path) -> None:
    with database_session(tmp_path / "audit.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        survivor, _absorbed, _, website_id, _ = _fixture(connection)
        connection.commit()
        before = {
            "observations": [tuple(row) for row in connection.execute("SELECT * FROM website_page_person_observations")],
            "reviews": [tuple(row) for row in connection.execute("SELECT * FROM person_observation_review_queue")],
            "website": tuple(connection.execute("SELECT status, website_kind, is_primary FROM websites WHERE id = ?", (website_id,)).fetchone()),
        }
        audit = audit_person(connection, survivor)
        assert audit["person"]["person_id"] == survivor
        assert audit["traceability"]["status"] == "traceable"
        assert len(audit["evidence"]) == 1
        observation = audit["evidence"][0]
        assert observation["page"]["url"] == "https://home.example/team"
        assert observation["website"]["website_id"] == website_id
        assert observation["entity"]["canonical_name"] == "Home"
        assert observation["traceability"] == "traceable"
        assert audit["reviews"][0]["status"] == "accepted"
        assert audit["affiliations"][0]["active"] == 1
        assert audit["contact_points"][0]["active"] == 1
        assert audit_people_list(connection) == audit_people_list(connection)
        assert before["observations"] == [tuple(row) for row in connection.execute("SELECT * FROM website_page_person_observations")]
        assert before["reviews"] == [tuple(row) for row in connection.execute("SELECT * FROM person_observation_review_queue")]
        assert before["website"] == tuple(connection.execute("SELECT status, website_kind, is_primary FROM websites WHERE id = ?", (website_id,)).fetchone())


def test_merge_and_rollback_history_and_historical_listing_are_audited(tmp_path: Path) -> None:
    with database_session(tmp_path / "history.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        survivor, absorbed, _, _, _ = _fixture(connection)
        connection.commit()
        merge = merge_people(connection, PersonMergeDecision(survivor, absorbed, "test", "audit merge"))
        merged_audit = audit_person(connection, survivor)
        assert merged_audit["merge_history"][0]["merge_id"] == merge.merge_history_id
        assert merged_audit["merge_history"][0]["state"] == "active"
        assert merged_audit["historical_affiliations"]
        assert merged_audit["historical_contact_points"]
        assert audit_people_list(connection) and absorbed not in {row["person_id"] for row in audit_people_list(connection)}
        assert absorbed in {row["person_id"] for row in audit_people_list(connection, include_historical=True)}
        rollback_person_merge(connection, merge.merge_history_id, actor="test", reason="audit rollback")
        rolled = audit_person(connection, survivor)
        assert rolled["merge_history"][0]["state"] == "rolled_back"
        assert rolled["merge_history"][0]["rollback_reason"] == "audit rollback"


def test_anomalies_are_deterministic_and_non_mutating(tmp_path: Path) -> None:
    with database_session(tmp_path / "anomalies.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        survivor, _, _, _, _ = _fixture(connection)
        connection.commit()
        connection.execute("DELETE FROM person_evidence WHERE person_id = ?", (survivor,))
        connection.commit()
        first = audit_person(connection, survivor)
        second = audit_person(connection, survivor)
        assert first["anomalies"] == second["anomalies"]
        assert first["anomalies"][0]["code"] == "active_person_zero_evidence"


def test_rejected_only_and_conflicting_contact_anomalies(tmp_path: Path) -> None:
    with database_session(tmp_path / "contact-anomalies.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        survivor, _, _, _, _ = _fixture(connection, conflict=True)
        connection.execute("UPDATE person_observation_review_queue SET status = 'rejected' WHERE observation_id IN (SELECT observation_id FROM person_evidence WHERE person_id = ?)", (survivor,))
        connection.execute("INSERT INTO person_contact_points (person_id, contact_type, observed_value, normalized_value, confidence, source_observation_id) SELECT ?, 'email', 'third@example.ca', 'third@example.ca', .5, pe.observation_id FROM person_evidence AS pe WHERE pe.person_id = ? LIMIT 1", (survivor, survivor))
        connection.commit()
        codes = {row["code"] for row in audit_person(connection, survivor)["anomalies"]}
        assert "rejected_only_evidence" in codes
        assert "conflicting_active_emails" in codes


def test_csv_export_is_deterministic_and_preserves_history(tmp_path: Path) -> None:
    with database_session(tmp_path / "export.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        survivor, absorbed, _, _, _ = _fixture(connection)
        connection.commit()
        merge_people(connection, PersonMergeDecision(survivor, absorbed, "test", "export merge"))
        first_dir = tmp_path / "export-one"
        second_dir = tmp_path / "export-two"
        export_people_csv(connection, first_dir)
        export_people_csv(connection, second_dir)
        files = sorted(path.name for path in first_dir.iterdir())
        assert files == [
            "people.csv",
            "person_affiliations.csv",
            "person_anomalies.csv",
            "person_contacts.csv",
            "person_merge_history.csv",
            "person_observations.csv",
            "person_reviews.csv",
            "person_triage.csv",
        ]
        assert len((first_dir / "person_merge_history.csv").read_text(encoding="utf-8").splitlines()) == 2
        for path in first_dir.iterdir():
            assert path.read_bytes() == (second_dir / path.name).read_bytes()
        invalid = tmp_path / "not-a-directory.txt"
        invalid.write_text("existing", encoding="utf-8")
        with pytest.raises(PersonResolutionError):
            export_people_csv(connection, invalid)
