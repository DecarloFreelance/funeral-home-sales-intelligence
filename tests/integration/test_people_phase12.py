from __future__ import annotations

from pathlib import Path

from canada_funeral_intel.people.audit import export_people_csv
from canada_funeral_intel.people.merge import merge_people
from canada_funeral_intel.people.models import PersonMergeDecision
from canada_funeral_intel.people.triage import (
    TriageFilters,
    TriageSeverity,
    triage_people,
)
from canada_funeral_intel.storage.database import database_session
from canada_funeral_intel.storage.migrations import apply_pending_migrations
from tests.integration.test_people_merge_phase10 import _fixture

MIGRATIONS = Path(__file__).resolve().parents[2] / "database" / "migrations"


def test_triage_severity_ordering_and_details(tmp_path: Path) -> None:
    with database_session(tmp_path / "triage.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        critical_survivor, critical_absorbed, _, _, _ = _fixture(connection)
        high_survivor, _, _, _, _ = _fixture(connection)
        medium_survivor, _, _, _, _ = _fixture(connection)
        connection.commit()
        critical_merge = merge_people(
            connection,
            PersonMergeDecision(critical_survivor, critical_absorbed, "test", "triage"),
        )
        connection.execute(
            "UPDATE people SET status = 'active' WHERE id = ?", (critical_absorbed,)
        )
        connection.execute(
            "DELETE FROM person_evidence WHERE person_id = ?", (high_survivor,)
        )
        connection.execute(
            "INSERT INTO person_contact_points (person_id, contact_type, observed_value, normalized_value, confidence, source_observation_id) SELECT ?, 'email', 'other@example.ca', 'other@example.ca', .5, observation_id FROM person_evidence WHERE person_id = ? LIMIT 1",
            (medium_survivor, medium_survivor),
        )
        connection.commit()
        records = triage_people(connection, TriageFilters())
        by_id = {row["person_id"]: row for row in records}
        assert by_id[critical_survivor]["severity"] == TriageSeverity.CRITICAL.value
        assert "merge_state_inconsistent" in by_id[critical_survivor]["anomaly_codes"]
        assert by_id[critical_survivor]["anomalies"][0]["supporting_ids"][
            "merge_ids"
        ] == [critical_merge.merge_history_id]
        assert by_id[high_survivor]["severity"] == TriageSeverity.HIGH.value
        assert (
            by_id[critical_survivor]["triage_priority"]
            < by_id[high_survivor]["triage_priority"]
        )
        assert records == sorted(
            records,
            key=lambda row: (
                row["triage_priority"],
                -row["anomaly_count"],
                row["person_id"],
            ),
        )


def test_triage_filters_use_relational_provenance_and_branch_isolation(
    tmp_path: Path,
) -> None:
    with database_session(tmp_path / "filters.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        person_a, person_b, branch_a, website_id, page_id = _fixture(
            connection, branch=True
        )
        branch_b = int(
            connection.execute(
                "INSERT INTO entities (entity_type, canonical_name) VALUES ('branch', 'Branch B')"
            ).lastrowid
        )
        connection.execute(
            "UPDATE person_affiliations SET entity_id = ? WHERE person_id = ?",
            (branch_b, person_b),
        )
        connection.commit()
        assert {
            row["person_id"]
            for row in triage_people(connection, TriageFilters(entity_id=branch_a))
        } == {person_a, person_b}
        assert [
            row["person_id"]
            for row in triage_people(connection, TriageFilters(branch_id=branch_a))
        ] == [person_a]
        assert (
            triage_people(connection, TriageFilters(branch_id=branch_b))[0]["person_id"]
            == person_b
        )
        assert {
            row["person_id"]
            for row in triage_people(connection, TriageFilters(website_id=website_id))
        } == {person_a, person_b}
        assert {
            row["person_id"]
            for row in triage_people(connection, TriageFilters(page_id=page_id))
        } == {person_a, person_b}
        assert triage_people(connection, TriageFilters(has_email=True))
        assert triage_people(connection, TriageFilters(has_phone=True))
        assert triage_people(connection, TriageFilters(review_status="accepted"))
        assert triage_people(connection, TriageFilters(limit=1))


def test_triage_historical_and_read_only_export(tmp_path: Path) -> None:
    with database_session(tmp_path / "historical.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        survivor, absorbed, _, _, _ = _fixture(connection)
        connection.commit()
        merge_people(
            connection,
            PersonMergeDecision(survivor, absorbed, "test", "triage history"),
        )
        before = [
            tuple(row)
            for row in connection.execute("SELECT id, status FROM people ORDER BY id")
        ]
        assert absorbed not in {row["person_id"] for row in triage_people(connection)}
        assert absorbed in {
            row["person_id"]
            for row in triage_people(connection, TriageFilters(include_historical=True))
        }
        first = tmp_path / "export-one"
        second = tmp_path / "export-two"
        export_people_csv(connection, first, include_historical=True)
        export_people_csv(connection, second, include_historical=True)
        assert (first / "person_triage.csv").read_bytes() == (
            second / "person_triage.csv"
        ).read_bytes()
        assert (
            "triage_priority"
            in (first / "person_triage.csv").read_text(encoding="utf-8").splitlines()[0]
        )
        assert before == [
            tuple(row)
            for row in connection.execute("SELECT id, status FROM people ORDER BY id")
        ]
