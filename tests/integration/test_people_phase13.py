from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from canada_funeral_intel.people.audit import export_people_csv
from canada_funeral_intel.people.dispositions import (
    DispositionStatus,
    decide_disposition,
    disposition_history,
    fingerprint_anomaly,
    list_dispositions,
    show_disposition,
    sync_dispositions,
)
from canada_funeral_intel.people.models import PersonResolutionError
from canada_funeral_intel.people.triage import TriageFilters, triage_people
from canada_funeral_intel.storage.database import database_session
from canada_funeral_intel.storage.migrations import apply_pending_migrations
from tests.integration.test_people_merge_phase10 import _fixture

MIGRATIONS = Path(__file__).resolve().parents[2] / "database" / "migrations"


def _open_anomaly(connection, person_id: int) -> dict[str, object]:
    connection.execute("DELETE FROM person_evidence WHERE person_id = ?", (person_id,))
    connection.commit()
    return triage_people(connection, TriageFilters(person_id=person_id))[0]["anomalies"][0]


def test_fingerprint_is_stable_and_structured(tmp_path: Path) -> None:
    anomaly = {"code": "x", "supporting_ids": {"person_ids": [1, 1], "observation_ids": [3, 2], "contact_ids": []}, "values": ["b", "a"]}
    same = {"code": "x", "supporting_ids": {"person_ids": [1], "observation_ids": [2, 3], "contact_ids": []}, "values": ["a", "b"]}
    assert fingerprint_anomaly(1, anomaly) == fingerprint_anomaly(1, same)
    assert fingerprint_anomaly(1, {**same, "values": ["a", "c"]}) != fingerprint_anomaly(1, same)
    assert fingerprint_anomaly(1, same) == fingerprint_anomaly(1, {**same, "timestamp": "different"})


def test_disposition_lifecycle_and_exact_instance_validation(tmp_path: Path) -> None:
    with database_session(tmp_path / "lifecycle.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        person_id, _, _, website_id, _ = _fixture(connection)
        anomaly = _open_anomaly(connection, person_id)
        fingerprint = anomaly["fingerprint"]
        result = decide_disposition(connection, person_id=person_id, anomaly_code=anomaly["code"], fingerprint=fingerprint, status=DispositionStatus.DISMISSED, actor="alex", note="accepted legacy gap")
        assert result.changed is True
        assert decide_disposition(connection, person_id=person_id, anomaly_code=anomaly["code"], fingerprint=fingerprint, status=DispositionStatus.DISMISSED, actor="alex").changed is False
        reopened = decide_disposition(connection, person_id=person_id, anomaly_code=anomaly["code"], fingerprint=fingerprint, status=DispositionStatus.REOPENED, actor="sam")
        assert reopened.status is DispositionStatus.REOPENED
        acknowledged = decide_disposition(connection, person_id=person_id, anomaly_code=anomaly["code"], fingerprint=fingerprint, status=DispositionStatus.ACKNOWLEDGED, actor="sam")
        assert acknowledged.status is DispositionStatus.ACKNOWLEDGED
        with pytest.raises(PersonResolutionError):
            decide_disposition(connection, person_id=person_id, anomaly_code=anomaly["code"], fingerprint="bad", status=DispositionStatus.DISMISSED, actor="sam")
        with pytest.raises(PersonResolutionError):
            decide_disposition(connection, person_id=person_id, anomaly_code=anomaly["code"], fingerprint=fingerprint, status=DispositionStatus.DISMISSED, actor=" ")
        triage = triage_people(connection, TriageFilters(person_id=person_id))[0]
        assert triage["anomalies"][0]["disposition"]["status"] == "acknowledged"
        assert triage_people(connection, TriageFilters(disposition_status="acknowledged"))[0]["person_id"] == person_id
        assert triage_people(connection, TriageFilters(unreviewed_only=True)) == []
        assert tuple(connection.execute("SELECT status, website_kind, is_primary FROM websites WHERE id = ?", (website_id,)).fetchone()) == ("review", "official", 0)


def test_sync_stales_changed_fingerprint_and_is_idempotent(tmp_path: Path) -> None:
    with database_session(tmp_path / "stale.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        person_id, _, _, _, _ = _fixture(connection)
        anomaly = _open_anomaly(connection, person_id)
        result = decide_disposition(connection, person_id=person_id, anomaly_code=anomaly["code"], fingerprint=anomaly["fingerprint"], status=DispositionStatus.DISMISSED, actor="alex")
        connection.execute("INSERT INTO person_evidence (person_id, observation_id, review_decision) SELECT ?, observation_id, 'accepted' FROM person_observation_review_queue LIMIT 1", (person_id,))
        connection.commit()
        synced = sync_dispositions(connection, person_id=person_id)
        assert synced["marked_stale"] == 1
        assert sync_dispositions(connection, person_id=person_id)["marked_stale"] == 0
        stored = list_dispositions(connection, person_id=person_id, include_stale=True)
        assert stored[0]["status"] == "stale"
        assert show_disposition(connection, result.disposition_id)["current_anomaly"] is None
        assert len(disposition_history(connection, result.disposition_id)) == 2
        with pytest.raises(PersonResolutionError):
            decide_disposition(connection, person_id=person_id, anomaly_code=anomaly["code"], fingerprint=anomaly["fingerprint"], status=DispositionStatus.ACKNOWLEDGED, actor="alex")


def test_history_is_immutable_and_exports_are_deterministic(tmp_path: Path) -> None:
    with database_session(tmp_path / "export.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        person_id, _, _, _, _ = _fixture(connection)
        anomaly = _open_anomaly(connection, person_id)
        result = decide_disposition(connection, person_id=person_id, anomaly_code=anomaly["code"], fingerprint=anomaly["fingerprint"], status=DispositionStatus.ACKNOWLEDGED, actor="alex")
        history_id = int(connection.execute("SELECT id FROM person_anomaly_disposition_history WHERE disposition_id = ?", (result.disposition_id,)).fetchone()[0])
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE person_anomaly_disposition_history SET note = 'tamper' WHERE id = ?", (history_id,))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM person_anomaly_disposition_history WHERE id = ?", (history_id,))
        first, second = tmp_path / "one", tmp_path / "two"
        export_people_csv(connection, first)
        export_people_csv(connection, second)
        assert (first / "person_anomaly_dispositions.csv").read_bytes() == (second / "person_anomaly_dispositions.csv").read_bytes()
        assert (first / "person_anomaly_disposition_history.csv").read_bytes() == (second / "person_anomaly_disposition_history.csv").read_bytes()
