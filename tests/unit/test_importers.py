from __future__ import annotations

import json

import pytest

from canada_funeral_intel.collectors.importers import (
    ImportFrameworkError,
    parse_csv,
    parse_json,
    payload_checksum,
)


def test_parse_csv_preserves_original_field_values() -> None:
    result = parse_csv(
        'id,name,postal\n1,"Maison funéraire Étoile","T2P 1J9"\n',
        external_id_field="id",
    )

    assert result.records_seen == 1
    assert result.errors == ()
    assert len(result.rows) == 1

    row = result.rows[0]
    assert row.row_number == 2
    assert row.external_record_id == "1"

    payload = json.loads(row.raw_payload)
    assert payload == {
        "id": "1",
        "name": "Maison funéraire Étoile",
        "postal": "T2P 1J9",
    }
    assert row.checksum == payload_checksum(row.raw_payload)


def test_parse_csv_reports_extra_values_as_row_error() -> None:
    result = parse_csv("id,name\n1,Alpha,extra\n", external_id_field="id")

    assert result.records_seen == 1
    assert result.rows == ()
    assert len(result.errors) == 1
    assert result.errors[0].row_number == 2
    assert "more values than the header" in result.errors[0].message


def test_parse_csv_rejects_duplicate_headers() -> None:
    with pytest.raises(ImportFrameworkError, match="must be unique"):
        parse_csv("id,id\n1,2\n")


def test_parse_json_preserves_original_types_and_unicode() -> None:
    result = parse_json(
        '[{"id":7,"active":true,"name":"Étoile","count":3}]',
        external_id_field="id",
    )

    assert result.errors == ()
    row = result.rows[0]
    assert row.external_record_id == "7"
    assert json.loads(row.raw_payload) == {
        "id": 7,
        "active": True,
        "name": "Étoile",
        "count": 3,
    }


def test_parse_json_reports_non_object_rows() -> None:
    result = parse_json('[{"id":"a"}, 42, "bad"]', external_id_field="id")

    assert len(result.rows) == 1
    assert len(result.errors) == 2
    assert result.records_seen == 3
    assert [error.row_number for error in result.errors] == [2, 3]


def test_parse_json_rejects_non_list_root() -> None:
    with pytest.raises(ImportFrameworkError, match="top-level list"):
        parse_json('{"id":1}')


def test_external_id_must_be_scalar() -> None:
    result = parse_json('[{"id":{"nested":1},"name":"Alpha"}]', external_id_field="id")

    assert result.rows == ()
    assert len(result.errors) == 1
    assert "must contain a scalar value" in result.errors[0].message


def test_payload_checksum_is_stable_and_sensitive() -> None:
    first = payload_checksum('{"name":"Alpha"}')
    second = payload_checksum('{"name":"Alpha"}')
    changed = payload_checksum('{"name":"alpha"}')

    assert first == second
    assert first != changed
    assert len(first) == 64
