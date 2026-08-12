from __future__ import annotations

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
    list_website_review_queue,
)
from canada_funeral_intel.verification.storage import (
    make_website_candidate,
    queue_website_for_review,
    upsert_website_candidate,
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
