from __future__ import annotations

import json
from pathlib import Path

import pytest

from canada_funeral_intel.collectors.import_execution import import_file
from canada_funeral_intel.collectors.importers import ImportFormat
from canada_funeral_intel.collectors.source_registry import load_source_registry
from canada_funeral_intel.collectors.source_registry_storage import (
    seed_source_registry,
)
from canada_funeral_intel.normalization.execution import (
    NormalizationExecutionError,
    normalize_source_records,
)
from canada_funeral_intel.storage import database_session
from canada_funeral_intel.storage.migrations import apply_pending_migrations

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "database" / "migrations"
REGISTRY = ROOT / "config" / "sources.json"


def _prepare_database(tmp_path: Path) -> tuple[Path, int]:
    database_path = tmp_path / "normalization.sqlite3"
    with database_session(database_path) as connection:
        apply_pending_migrations(connection, MIGRATIONS)
        seed_source_registry(connection, load_source_registry(REGISTRY))
        connection.commit()
        row = connection.execute(
            "SELECT id FROM source_datasets WHERE name = ?",
            ("Manual Canadian Funeral Home Source",),
        ).fetchone()
    assert row is not None
    return database_path, int(row["id"])


def test_normalize_source_records_persists_supported_fields(tmp_path: Path) -> None:
    database_path, dataset_id = _prepare_database(tmp_path)
    input_path = tmp_path / "records.json"
    input_path.write_text(
        json.dumps(
            [
                {
                    "id": "A-1",
                    "name": "Maison funéraire Étoile Inc.",
                    "address": "Suite 205, 123 Main St SW",
                    "city": " Calgary ",
                    "province": "Alberta",
                    "postal": "t2p1j9",
                    "phone": "403-555-0100",
                    "email": "Info@Example.CA",
                    "website": "Example.CA/contact#staff",
                    "domain": "www.Example.CA",
                    "ignored": "keep raw only",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with database_session(database_path) as connection:
        import_file(
            connection,
            source_dataset_id=dataset_id,
            input_path=input_path,
            input_format=ImportFormat.JSON,
            external_id_field="id",
        )
        result = normalize_source_records(
            connection,
            source_dataset_id=dataset_id,
        )
        rows = connection.execute(
            """
            SELECT field_name, original_value, normalized_value,
                   normalizer_name, normalizer_version, warnings
            FROM normalized_values
            ORDER BY field_name
            """
        ).fetchall()

    assert result.records_seen == 1
    assert result.values_inserted == 9
    assert result.values_unchanged == 0
    assert result.fields_skipped == 2

    values = {row["field_name"]: row for row in rows}
    assert values["business_name"]["normalized_value"] == "funeral home etoile"
    assert values["address"]["normalized_value"] == "123 main street southwest unit 205"
    assert values["city"]["normalized_value"] == "Calgary"
    assert values["province"]["normalized_value"] == "AB"
    assert values["postal_code"]["normalized_value"] == "T2P 1J9"
    assert values["phone"]["normalized_value"] == "+14035550100"
    assert values["email"]["normalized_value"] == "info@example.ca"
    assert values["url"]["normalized_value"] == "https://example.ca/contact"
    assert values["domain"]["normalized_value"] == "example.ca"
    assert values["province"]["normalizer_name"] == "province"
    assert values["province"]["normalizer_version"] == "1"
    assert values["phone"]["normalizer_version"] == "2"
    assert json.loads(values["province"]["warnings"])


def test_normalization_is_idempotent_for_same_source_record(tmp_path: Path) -> None:
    database_path, dataset_id = _prepare_database(tmp_path)
    input_path = tmp_path / "records.json"
    input_path.write_text(
        '[{"id":"A-1","name":"Alpha Funeral Home","province":"AB"}]',
        encoding="utf-8",
    )

    with database_session(database_path) as connection:
        import_file(
            connection,
            source_dataset_id=dataset_id,
            input_path=input_path,
            input_format=ImportFormat.JSON,
            external_id_field="id",
        )
        first = normalize_source_records(connection)
        second = normalize_source_records(connection)
        count = connection.execute("SELECT COUNT(*) FROM normalized_values").fetchone()[
            0
        ]

    assert first.values_inserted == 2
    assert second.values_inserted == 0
    assert second.values_unchanged == 2
    assert count == 2


def test_normalization_can_be_scoped_to_source_dataset(tmp_path: Path) -> None:
    database_path, manual_id = _prepare_database(tmp_path)

    with database_session(database_path) as connection:
        other = connection.execute(
            "SELECT id FROM source_datasets WHERE id != ? ORDER BY id LIMIT 1",
            (manual_id,),
        ).fetchone()
        assert other is not None
        other_id = int(other["id"])

        connection.execute(
            """
            INSERT INTO source_records (
                source_dataset_id,
                raw_payload,
                payload_format,
                retrieved_at,
                checksum
            )
            VALUES (?, ?, 'json', '2026-08-08T12:00:00+00:00', ?)
            """,
            (
                other_id,
                '{"name":"Other Funeral Home"}',
                "other-checksum",
            ),
        )
        connection.execute(
            """
            INSERT INTO source_records (
                source_dataset_id,
                raw_payload,
                payload_format,
                retrieved_at,
                checksum
            )
            VALUES (?, ?, 'json', '2026-08-08T12:00:00+00:00', ?)
            """,
            (
                manual_id,
                '{"name":"Manual Funeral Home"}',
                "manual-checksum",
            ),
        )
        connection.commit()

        result = normalize_source_records(
            connection,
            source_dataset_id=manual_id,
        )
        rows = connection.execute(
            """
            SELECT nv.normalized_value
            FROM normalized_values AS nv
            JOIN source_records AS sr ON sr.id = nv.source_record_id
            WHERE sr.source_dataset_id = ?
            """,
            (manual_id,),
        ).fetchall()

    assert result.records_seen == 1
    assert [row["normalized_value"] for row in rows] == ["manual funeral home"]


def test_nested_supported_field_is_skipped_without_mutating_raw_payload(
    tmp_path: Path,
) -> None:
    database_path, dataset_id = _prepare_database(tmp_path)
    raw_payload = '{"name":{"text":"Alpha"},"phone":["403-555-0100"]}'

    with database_session(database_path) as connection:
        connection.execute(
            """
            INSERT INTO source_records (
                source_dataset_id,
                raw_payload,
                payload_format,
                retrieved_at,
                checksum
            )
            VALUES (?, ?, 'json', '2026-08-08T12:00:00+00:00', 'nested')
            """,
            (dataset_id, raw_payload),
        )
        connection.commit()

        result = normalize_source_records(connection)
        stored = connection.execute(
            "SELECT raw_payload FROM source_records"
        ).fetchone()["raw_payload"]

    assert result.values_inserted == 0
    assert result.fields_skipped == 2
    assert stored == raw_payload


def test_invalid_source_dataset_id_is_rejected(tmp_path: Path) -> None:
    database_path, _ = _prepare_database(tmp_path)
    with (
        database_session(database_path) as connection,
        pytest.raises(
            NormalizationExecutionError,
            match="source_dataset_id",
        ),
    ):
        normalize_source_records(connection, source_dataset_id=0)


def test_invalid_raw_payload_rolls_back_normalization_batch(tmp_path: Path) -> None:
    database_path, dataset_id = _prepare_database(tmp_path)

    with database_session(database_path) as connection:
        connection.executemany(
            """
            INSERT INTO source_records (
                source_dataset_id,
                raw_payload,
                payload_format,
                retrieved_at,
                checksum
            )
            VALUES (?, ?, 'json', '2026-08-08T12:00:00+00:00', ?)
            """,
            [
                (dataset_id, '{"name":"Valid Funeral Home"}', "valid"),
                (dataset_id, "{not-json", "invalid"),
            ],
        )
        connection.commit()

        with pytest.raises(
            NormalizationExecutionError,
            match="invalid JSON",
        ):
            normalize_source_records(connection)

        count = connection.execute("SELECT COUNT(*) FROM normalized_values").fetchone()[
            0
        ]

    assert count == 0
