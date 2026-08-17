from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

import pytest

from canada_funeral_intel.storage import database_session
from canada_funeral_intel.storage.migrations import (
    apply_pending_migrations,
)
from canada_funeral_intel.verification.models import (
    WebsiteKind,
    WebsiteReviewStatus,
)
from canada_funeral_intel.verification.review import (
    WebsiteReviewError,
    apply_website_review_decision,
    export_website_review_csv,
    import_website_review_csv,
    list_website_review_queue,
)
from canada_funeral_intel.verification.storage import (
    make_website_candidate,
    queue_website_for_review,
    upsert_website_candidate,
)
from canada_funeral_intel.verification.website_cli import (
    run_website_review_interactive,
)

ROOT = Path(__file__).resolve().parents[2]
MIGRATION_DIR = ROOT / "database" / "migrations"


def _seed_website(
    connection: sqlite3.Connection,
    *,
    url: str = "https://example.ca/",
    website_kind: WebsiteKind = WebsiteKind.CANDIDATE,
) -> tuple[int, int]:
    cursor = connection.execute(
        """
        INSERT INTO entities (
            entity_type,
            canonical_name
        )
        VALUES (
            'organization',
            'Fixture'
        )
        """
    )
    assert cursor.lastrowid is not None
    entity_id = int(cursor.lastrowid)

    connection.commit()

    candidate = make_website_candidate(
        entity_id=entity_id,
        url=url,
        discovery_method="manual",
        confidence=0.55,
        website_kind=website_kind,
    )

    website_id = upsert_website_candidate(
        connection,
        candidate,
    ).website_id

    queue_id = queue_website_for_review(
        connection,
        website_id,
    )

    return entity_id, queue_id


def test_website_review_approval_selects_primary(
    tmp_path: Path,
) -> None:
    with database_session(tmp_path / "approved.sqlite3") as connection:
        apply_pending_migrations(
            connection,
            MIGRATION_DIR,
        )

        entity_id, queue_id = _seed_website(connection)

        result = apply_website_review_decision(
            connection,
            queue_id=queue_id,
            status=WebsiteReviewStatus.APPROVED,
            reviewer_note="official site confirmed",
        )

        assert result.entity_id == entity_id
        assert result.website_status.value == "selected"
        assert result.is_primary is True

        row = connection.execute(
            """
            SELECT
                website_kind,
                status,
                is_primary
            FROM websites
            """
        ).fetchone()

        assert tuple(row) == (
            "official",
            "selected",
            1,
        )


def test_website_review_rejection_never_primary(
    tmp_path: Path,
) -> None:
    with database_session(tmp_path / "rejected.sqlite3") as connection:
        apply_pending_migrations(
            connection,
            MIGRATION_DIR,
        )

        _, queue_id = _seed_website(connection)

        result = apply_website_review_decision(
            connection,
            queue_id=queue_id,
            status=WebsiteReviewStatus.REJECTED,
        )

        assert result.website_status.value == "rejected"
        assert result.is_primary is False


def test_website_review_deferred_remains_review(
    tmp_path: Path,
) -> None:
    with database_session(tmp_path / "deferred.sqlite3") as connection:
        apply_pending_migrations(
            connection,
            MIGRATION_DIR,
        )

        _, queue_id = _seed_website(connection)

        result = apply_website_review_decision(
            connection,
            queue_id=queue_id,
            status=WebsiteReviewStatus.DEFERRED,
            reviewer_note="needs verification",
        )

        assert result.website_status.value == "review"
        assert result.is_primary is False

        entries = list_website_review_queue(
            connection,
            status=WebsiteReviewStatus.DEFERRED,
        )

        assert len(entries) == 1
        assert entries[0].reviewer_note == "needs verification"


def test_social_profile_cannot_be_approved_primary(
    tmp_path: Path,
) -> None:
    with database_session(tmp_path / "social.sqlite3") as connection:
        apply_pending_migrations(
            connection,
            MIGRATION_DIR,
        )

        _, queue_id = _seed_website(
            connection,
            url="https://facebook.com/example",
            website_kind=WebsiteKind.SOCIAL,
        )

        with pytest.raises(
            WebsiteReviewError,
            match="Social profiles",
        ):
            apply_website_review_decision(
                connection,
                queue_id=queue_id,
                status=WebsiteReviewStatus.APPROVED,
            )


def test_second_primary_for_entity_is_rejected(
    tmp_path: Path,
) -> None:
    with database_session(tmp_path / "primary.sqlite3") as connection:
        apply_pending_migrations(
            connection,
            MIGRATION_DIR,
        )

        entity_id, first_queue_id = _seed_website(
            connection,
            url="https://one.example.ca/",
        )

        first = apply_website_review_decision(
            connection,
            queue_id=first_queue_id,
            status=WebsiteReviewStatus.APPROVED,
        )

        assert first.is_primary is True

        second = make_website_candidate(
            entity_id=entity_id,
            url="https://two.example.ca/",
            discovery_method="manual",
            confidence=0.60,
        )

        second_id = upsert_website_candidate(
            connection,
            second,
        ).website_id

        second_queue_id = queue_website_for_review(
            connection,
            second_id,
        )

        with pytest.raises(
            WebsiteReviewError,
            match="already has primary website",
        ):
            apply_website_review_decision(
                connection,
                queue_id=second_queue_id,
                status=WebsiteReviewStatus.APPROVED,
            )


def test_review_csv_export_and_import_preserve_decision_semantics(
    tmp_path: Path,
) -> None:
    with database_session(tmp_path / "csv.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATION_DIR)
        _, queue_id = _seed_website(connection)
        output_path = tmp_path / "website-review.csv"

        exported = export_website_review_csv(
            connection,
            output_path=output_path,
        )

        assert exported["rows"] == 1
        with output_path.open(newline="", encoding="utf-8") as handle:
            row = next(csv.DictReader(handle))
        assert row["queue_id"] == str(queue_id)
        assert row["url"] == "https://example.ca/"

        rows = list(csv.DictReader(output_path.open(newline="", encoding="utf-8")))
        rows[0]["decision"] = "approved"
        rows[0]["reviewer_note"] = "confirmed in spreadsheet"
        with output_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

        imported = import_website_review_csv(
            connection,
            input_path=output_path,
        )

        assert imported["decisions_applied"] == 1
        entry = list_website_review_queue(
            connection,
            status=WebsiteReviewStatus.APPROVED,
        )
        assert len(entry) == 1
        assert entry[0].review_status is WebsiteReviewStatus.APPROVED


def test_review_csv_invalid_rows_do_not_mutate_queue(
    tmp_path: Path,
) -> None:
    with database_session(tmp_path / "invalid-csv.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATION_DIR)
        _, queue_id = _seed_website(connection)
        input_path = tmp_path / "invalid.csv"
        input_path.write_text(
            f"queue_id,decision,reviewer_note\n{queue_id},not-a-decision,bad\n",
            encoding="utf-8",
        )

        with pytest.raises(WebsiteReviewError, match="invalid decision"):
            import_website_review_csv(connection, input_path=input_path)

        pending = list_website_review_queue(
            connection,
            status=WebsiteReviewStatus.PENDING,
        )
        assert len(pending) == 1
        assert pending[0].queue_id == queue_id


def test_interactive_review_uses_existing_decision_service(
    tmp_path: Path,
) -> None:
    with database_session(tmp_path / "interactive.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATION_DIR)
        _, first_queue_id = _seed_website(connection, url="https://first.ca/")
        _, second_queue_id = _seed_website(connection, url="https://second.ca/")
        answers = iter(("a", "confirmed official site", "", "s"))
        shown: list[str] = []

        result = run_website_review_interactive(
            connection,
            input_fn=lambda _prompt: next(answers),
            output_fn=shown.append,
        )

        assert result["approved"] == 1
        assert result["skipped"] == 1
        assert list_website_review_queue(
            connection,
            status=WebsiteReviewStatus.APPROVED,
        )[0].queue_id == first_queue_id
        assert list_website_review_queue(
            connection,
            status=WebsiteReviewStatus.PENDING,
        )[0].queue_id == second_queue_id
        assert any("https://first.ca/" in line for line in shown)


def test_interactive_review_can_group_shared_urls(
    tmp_path: Path,
) -> None:
    with database_session(tmp_path / "grouped-interactive.sqlite3") as connection:
        apply_pending_migrations(connection, MIGRATION_DIR)
        _seed_website(connection, url="https://shared.ca/")
        _seed_website(connection, url="https://shared.ca/")
        answers = iter(("a", "Shared official website", ""))
        shown: list[str] = []

        result = run_website_review_interactive(
            connection,
            group_domains=True,
            input_fn=lambda _prompt: next(answers),
            output_fn=shown.append,
        )

        assert result["groups_presented"] == 1
        assert result["approved"] == 2
        assert result["errors"] == 0
        assert any("Shared by:  2 entity relationships" in line for line in shown)
