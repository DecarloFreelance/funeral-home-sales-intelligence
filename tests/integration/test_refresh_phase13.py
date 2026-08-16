from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from canada_funeral_intel.refresh.fingerprints import (
    business_fact,
    page_observation,
    person_observation,
)
from canada_funeral_intel.refresh.models import RefreshObservation
from canada_funeral_intel.refresh.storage import (
    begin_run,
    complete_run,
    fail_run,
    list_changes,
    record_observation,
    show_run,
)
from canada_funeral_intel.storage.database import database_session
from canada_funeral_intel.storage.migrations import apply_pending_migrations

MIGRATIONS = Path(__file__).resolve().parents[2] / "database" / "migrations"
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _run(connection, reference_time: datetime) -> int:
    return begin_run(
        connection,
        run_type="website_page",
        scope_type="website",
        scope_value="1",
        reference_time=reference_time,
    )


def _item(value: str) -> RefreshObservation:
    key, digest = page_observation(
        website_id=1,
        normalized_url="https://example.ca/team",
        page_kind="team",
        content_hash=value,
        status_code=200,
        content_type="text/html",
    )
    return RefreshObservation("website_page", key, digest, 7)


def test_refresh_lifecycle_and_change_types(tmp_path: Path) -> None:
    with database_session(tmp_path / "refresh.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        first = _run(connection, T0)
        assert (
            record_observation(connection, run_id=first, observation=_item("a" * 64))[
                "status"
            ]
            == "inserted"
        )
        assert (
            record_observation(connection, run_id=first, observation=_item("a" * 64))[
                "status"
            ]
            == "unchanged"
        )
        assert complete_run(connection, first)["events"] == 1
        second = _run(connection, T0.replace(day=2))
        record_observation(connection, run_id=second, observation=_item("b" * 64))
        assert complete_run(connection, second)["events"] == 1
        third = _run(connection, T0.replace(day=3))
        assert complete_run(connection, third)["events"] == 1
        fourth = _run(connection, T0.replace(day=4))
        record_observation(connection, run_id=fourth, observation=_item("b" * 64))
        assert complete_run(connection, fourth)["events"] == 1
        assert [row["change_type"] for row in list_changes(connection)] == [
            "added",
            "changed",
            "missing",
            "reappeared",
        ]
        assert show_run(connection, third)["items"][0]["present"] == 0


def test_failed_run_is_not_a_baseline_and_duplicate_conflicts_are_rejected(
    tmp_path: Path,
) -> None:
    with database_session(tmp_path / "refresh.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        run_id = _run(connection, T0)
        record_observation(connection, run_id=run_id, observation=_item("a" * 64))
        assert (
            fail_run(connection, run_id=run_id, error_summary="fixture failure")[
                "status"
            ]
            == "failed"
        )
        with pytest.raises(ValueError, match="not running"):
            record_observation(connection, run_id=run_id, observation=_item("a" * 64))
        next_run = _run(connection, T0.replace(day=2))
        record_observation(connection, run_id=next_run, observation=_item("a" * 64))
        assert complete_run(connection, next_run)["events"] == 1
        assert list_changes(connection)[0]["change_type"] == "added"
        duplicate = _run(connection, T0.replace(day=3))
        record_observation(connection, run_id=duplicate, observation=_item("a" * 64))
        with pytest.raises(ValueError, match="conflicting duplicate"):
            record_observation(
                connection,
                run_id=duplicate,
                observation=RefreshObservation(
                    "website_page", _item("a" * 64).subject_key, "c" * 64, 8
                ),
            )


def test_fingerprints_ignore_timestamps_and_cover_all_supported_subjects() -> None:
    page_key, page_digest = page_observation(
        website_id=1,
        normalized_url="/team",
        page_kind="team",
        content_hash="a" * 64,
        status_code=200,
        content_type="text/html",
    )
    person_key, person_digest = person_observation(
        page_id=2,
        normalized_name="alex doe",
        normalized_role="director",
        normalized_email="",
        normalized_phone="",
        branch_context=None,
    )
    fact_key, fact_digest = business_fact(
        page_id=2,
        fact_key="chapel",
        scope="explicit",
        scope_entity_id=3,
        normalized_value="chapel",
        value_kind="enum",
        content_hash="a" * 64,
    )
    assert page_key and person_key and fact_key
    assert all(len(value) == 64 for value in (page_digest, person_digest, fact_digest))
    assert (
        page_observation(
            website_id=1,
            normalized_url="/team",
            page_kind="team",
            content_hash="a" * 64,
            status_code=200,
            content_type="text/html",
        )[1]
        == page_digest
    )


def test_change_events_are_immutable(tmp_path: Path) -> None:
    with database_session(tmp_path / "refresh.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        run_id = _run(connection, T0)
        record_observation(connection, run_id=run_id, observation=_item("a" * 64))
        complete_run(connection, run_id)
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE change_events SET reason_code='changed' WHERE id=1"
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("DELETE FROM change_events WHERE id=1")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE refresh_run_items SET present=0 WHERE refresh_run_id=?",
                (run_id,),
            )
