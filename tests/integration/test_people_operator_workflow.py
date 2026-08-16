from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from canada_funeral_intel.cli import main
from canada_funeral_intel.collectors.importers import ImportFormat
from canada_funeral_intel.people.models import PersonResolutionError, PersonReviewStatus
from canada_funeral_intel.people.resolution import (
    apply_person_review_decision,
    person_review_backlog,
    populate_person_review_queue,
    resolve_accepted_observation,
)
from canada_funeral_intel.pipeline.orchestrator import PipelineInput, create_run
from canada_funeral_intel.storage.database import database_session
from canada_funeral_intel.storage.migrations import apply_pending_migrations
from canada_funeral_intel.verification.page_discovery import discover_website_pages
from canada_funeral_intel.verification.probe import HTTPProbeResult
from tests.integration.test_website_phase8_people_integration import _seed

MIGRATIONS = Path(__file__).resolve().parents[2] / "database" / "migrations"


def _observation(
    connection, *, entity_id: int, website_id: int, page_id: int, name: str, number: int
) -> int:
    digest = hashlib.sha256(f"{name}-{number}".encode()).hexdigest()
    cursor = connection.execute(
        """
        INSERT INTO website_page_person_observations
        (website_page_id, website_id, entity_id, observed_name, normalized_name,
         role_title, normalized_role, email, normalized_email, phone, normalized_phone,
         branch_context, confidence, extraction_method, extractor_version,
         evidence_snippet, source_url, content_hash)
        VALUES (?, ?, ?, ?, ?, 'Funeral Director', 'funeral director', ?, ?, ?, ?,
                '', 0.9, 'structured_role_block', 'phase8-test', ?, ?, ?)
        """,
        (
            page_id,
            website_id,
            entity_id,
            name,
            name.casefold(),
            f"{name.casefold().replace(' ', '.')}@example.ca",
            f"{name.casefold().replace(' ', '.')}@example.ca",
            "403-555-0100",
            "4035550100",
            f"{name} — Funeral Director",
            f"https://example.ca/team/{number}",
            digest,
        ),
    )
    return int(cursor.lastrowid)


def test_backlog_classifies_all_observation_states_and_excludes_resolved(
    tmp_path: Path,
) -> None:
    with database_session(tmp_path / "backlog.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        entity_id, website_id, page_id = _seed(connection)
        missing = _observation(
            connection,
            entity_id=entity_id,
            website_id=website_id,
            page_id=page_id,
            name="Missing Review",
            number=1,
        )
        pending = _observation(
            connection,
            entity_id=entity_id,
            website_id=website_id,
            page_id=page_id,
            name="Pending Review",
            number=2,
        )
        deferred = _observation(
            connection,
            entity_id=entity_id,
            website_id=website_id,
            page_id=page_id,
            name="Deferred Review",
            number=3,
        )
        accepted = _observation(
            connection,
            entity_id=entity_id,
            website_id=website_id,
            page_id=page_id,
            name="Accepted Unresolved",
            number=4,
        )
        rejected = _observation(
            connection,
            entity_id=entity_id,
            website_id=website_id,
            page_id=page_id,
            name="Rejected Review",
            number=5,
        )
        resolved = _observation(
            connection,
            entity_id=entity_id,
            website_id=website_id,
            page_id=page_id,
            name="Resolved Review",
            number=6,
        )
        connection.commit()

        assert populate_person_review_queue(connection) == (6, 0)
        connection.execute(
            "DELETE FROM person_observation_review_queue WHERE observation_id = ?",
            (missing,),
        )
        connection.commit()
        queue = connection.execute(
            "SELECT id, observation_id FROM person_observation_review_queue ORDER BY observation_id"
        ).fetchall()
        statuses = {
            pending: "pending",
            deferred: "deferred",
            accepted: "accepted",
            rejected: "rejected",
            resolved: "accepted",
        }
        for row in queue:
            status = statuses[int(row["observation_id"])]
            if status == "pending":
                continue
            apply_person_review_decision(
                connection,
                queue_id=int(row["id"]),
                status=PersonReviewStatus(status),
            )
        resolve_accepted_observation(connection, resolved)

        result = person_review_backlog(connection, include_details=True)

    assert result["counts"] == {
        "missing_review": 1,
        "pending": 1,
        "deferred": 1,
        "accepted_unresolved": 1,
        "rejected": 1,
        "resolved": 1,
    }
    details = {
        row["observation_id"]: row["workflow_state"] for row in result["observations"]
    }
    assert details[missing] == "missing_review"
    assert details[accepted] == "accepted_unresolved"
    assert details[resolved] == "resolved"


def test_top_level_cli_executes_complete_manual_people_workflow(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "operator.sqlite3"
    body = b"""
    <html><body><div class="team-card">
      <h2>Alice Smith</h2><p>Funeral Director</p>
      <a href="mailto:alice@example.ca">alice@example.ca</a>
      <span>403-555-0100</span>
    </div></body></html>
    """

    def fake_probe(url: str, **kwargs: object) -> HTTPProbeResult:
        del kwargs
        return HTTPProbeResult(
            requested_url=url,
            final_url="https://redirected.example.ca/team",
            status_code=200,
            redirect_count=1,
            response_time_ms=1,
            content_type="text/html",
            canonical_url=None,
            error_message=None,
            body=body,
        )

    monkeypatch.setattr(
        "canada_funeral_intel.extraction.page_people.probe_http", fake_probe
    )
    monkeypatch.setenv("DATABASE_PATH", str(database_path))

    with database_session(database_path) as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        entity_id, website_id, page_id = _seed(connection)

    assert main(["website", "extract-people", "--website-id", str(website_id)]) == 0
    extracted = json.loads(capsys.readouterr().out)
    assert extracted["observations_inserted"] == 1

    assert main(["people", "people-review", "backlog"]) == 0
    before_populate = json.loads(capsys.readouterr().out)
    assert before_populate["counts"]["missing_review"] == 1

    assert main(["people", "people-review", "populate"]) == 0
    populated = json.loads(capsys.readouterr().out)
    assert populated["queue_entries_inserted"] == 1

    assert main(["people", "people-review", "list"]) == 0
    queue = json.loads(capsys.readouterr().out)
    queue_id = queue[0]["queue_id"]
    observation_id = queue[0]["observation_id"]

    assert (
        main(
            [
                "people",
                "people-review",
                "decide",
                "--queue-id",
                str(queue_id),
                "--status",
                "accepted",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert main(["people", "resolve", "--observation-id", str(observation_id)]) == 0
    resolved = json.loads(capsys.readouterr().out)

    with database_session(database_path) as connection:
        person = connection.execute(
            "SELECT id FROM people WHERE id = ?", (resolved["person_id"],)
        ).fetchone()
        affiliation = connection.execute(
            "SELECT entity_id, source_observation_id FROM person_affiliations WHERE person_id = ?",
            (resolved["person_id"],),
        ).fetchone()
        contact = connection.execute(
            "SELECT contact_type, source_observation_id FROM person_contact_points WHERE person_id = ?",
            (resolved["person_id"],),
        ).fetchone()
        evidence = connection.execute(
            "SELECT observation_id FROM person_evidence WHERE person_id = ?",
            (resolved["person_id"],),
        ).fetchone()
        page = connection.execute(
            "SELECT wp.website_id, w.entity_id FROM website_pages AS wp JOIN websites AS w ON w.id = wp.website_id WHERE wp.id = ?",
            (page_id,),
        ).fetchone()

    assert person is not None
    assert tuple(affiliation) == (entity_id, observation_id)
    assert tuple(contact) == ("email", observation_id)
    assert evidence["observation_id"] == observation_id
    assert tuple(page) == (website_id, entity_id)

    assert main(["people", "people-review", "backlog"]) == 0
    final_backlog = json.loads(capsys.readouterr().out)
    assert final_backlog["counts"]["accepted_unresolved"] == 0
    assert final_backlog["counts"]["resolved"] == 1


def test_review_boundaries_and_repeated_resolution_are_explicit(tmp_path: Path) -> None:
    with database_session(tmp_path / "boundaries.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        entity_id, website_id, page_id = _seed(connection)
        pending = _observation(
            connection,
            entity_id=entity_id,
            website_id=website_id,
            page_id=page_id,
            name="Pending",
            number=11,
        )
        deferred = _observation(
            connection,
            entity_id=entity_id,
            website_id=website_id,
            page_id=page_id,
            name="Deferred",
            number=12,
        )
        rejected = _observation(
            connection,
            entity_id=entity_id,
            website_id=website_id,
            page_id=page_id,
            name="Rejected",
            number=13,
        )
        accepted = _observation(
            connection,
            entity_id=entity_id,
            website_id=website_id,
            page_id=page_id,
            name="Accepted",
            number=14,
        )
        accepted_other = _observation(
            connection,
            entity_id=entity_id,
            website_id=website_id,
            page_id=page_id,
            name="Accepted Other",
            number=15,
        )
        connection.commit()
        assert populate_person_review_queue(connection) == (5, 0)
        queue = connection.execute(
            "SELECT id, observation_id FROM person_observation_review_queue ORDER BY observation_id"
        ).fetchall()
        by_observation = {int(row["observation_id"]): int(row["id"]) for row in queue}

        with pytest.raises(PersonResolutionError):
            resolve_accepted_observation(connection, pending)
        apply_person_review_decision(
            connection,
            queue_id=by_observation[deferred],
            status=PersonReviewStatus.DEFERRED,
        )
        apply_person_review_decision(
            connection,
            queue_id=by_observation[rejected],
            status=PersonReviewStatus.REJECTED,
        )
        apply_person_review_decision(
            connection,
            queue_id=by_observation[accepted],
            status=PersonReviewStatus.ACCEPTED,
        )
        apply_person_review_decision(
            connection,
            queue_id=by_observation[accepted_other],
            status=PersonReviewStatus.ACCEPTED,
        )
        with pytest.raises(PersonResolutionError):
            resolve_accepted_observation(connection, deferred)
        with pytest.raises(PersonResolutionError):
            resolve_accepted_observation(connection, rejected)
        person_id = resolve_accepted_observation(connection, accepted)
        other_person_id = resolve_accepted_observation(connection, accepted_other)
        assert resolve_accepted_observation(connection, accepted) == person_id
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM person_evidence WHERE observation_id = ?",
                (accepted,),
            ).fetchone()[0]
            == 1
        )
        assert other_person_id != person_id
        sources = connection.execute(
            "SELECT source_observation_id FROM person_affiliations WHERE source_observation_id IN (?, ?) ORDER BY source_observation_id",
            (accepted, accepted_other),
        ).fetchall()
        assert [int(row["source_observation_id"]) for row in sources] == [
            accepted,
            accepted_other,
        ]
        assert person_review_backlog(connection)["counts"]["accepted_unresolved"] == 0


def test_crawler_and_offline_pipeline_do_not_enter_people_workflow(
    monkeypatch,
    tmp_path: Path,
) -> None:
    with database_session(tmp_path / "crawler.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        _, website_id, _ = _seed(connection)

        monkeypatch.setattr(
            "canada_funeral_intel.extraction.page_people.extract_website_people",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("crawler invoked people extraction")
            ),
        )
        monkeypatch.setattr(
            "canada_funeral_intel.people.resolution.resolve_accepted_observation",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("crawler invoked people resolution")
            ),
        )
        monkeypatch.setattr(
            "canada_funeral_intel.verification.page_discovery.probe_http",
            lambda url, **kwargs: HTTPProbeResult(
                requested_url=url,
                final_url=url,
                status_code=200,
                redirect_count=0,
                response_time_ms=1,
                content_type="text/html",
                canonical_url=None,
                error_message=None,
                body=b"<html><body>Home</body></html>",
            ),
        )
        result = discover_website_pages(
            connection,
            website_id=website_id,
            user_agent="Fixture/1.0",
            timeout_seconds=5,
            max_redirects=2,
            max_pages=1,
            max_depth=0,
        )
        assert result.pages_persisted == 1

    database_path = tmp_path / "pipeline.sqlite3"
    input_path = tmp_path / "records.json"
    input_path.write_text(
        json.dumps([{"id": "a", "name": "Alpha Funeral Home"}]), encoding="utf-8"
    )
    monkeypatch.setattr(
        "canada_funeral_intel.extraction.page_people.extract_website_people",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("offline pipeline invoked people extraction")
        ),
    )
    monkeypatch.setattr(
        "canada_funeral_intel.people.resolution.resolve_accepted_observation",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("offline pipeline invoked people resolution")
        ),
    )
    with database_session(database_path) as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        connection.execute(
            "INSERT INTO source_datasets (id, name, source_type, jurisdiction) VALUES (1, 'Fixture', 'manual', 'CA')"
        )
        connection.commit()
        result = create_run(
            connection,
            PipelineInput(
                source_dataset_id=1,
                input_path=input_path,
                input_format=ImportFormat.JSON,
                external_id_field="id",
            ),
        )
    assert result["status"] == "completed"


def test_backlog_is_database_only(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "canada_funeral_intel.verification.probe.probe_http",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("backlog performed network retrieval")
        ),
    )
    with database_session(tmp_path / "read-only.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        entity_id, website_id, page_id = _seed(connection)
        _observation(
            connection,
            entity_id=entity_id,
            website_id=website_id,
            page_id=page_id,
            name="Read Only",
            number=20,
        )
        connection.commit()
        result = person_review_backlog(connection, include_details=True)
    assert result["counts"]["missing_review"] == 1
