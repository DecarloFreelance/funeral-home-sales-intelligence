from __future__ import annotations

import json

import pytest

from canada_funeral_intel.normalization.models import (
    NormalizationError,
    NormalizedValue,
    make_normalized_value,
)


def test_normalized_value_preserves_original_and_provenance() -> None:
    value = make_normalized_value(
        source_record_id=7,
        field_name="business_name",
        original_value="  Étoile Funéraire Inc.  ",
        normalized_value="Étoile Funéraire Inc.",
        normalizer_name="business_name",
        normalizer_version="1",
        warnings=("trimmed surrounding whitespace",),
        normalized_at="2026-08-08T12:00:00+00:00",
    )

    assert value.original_value == "  Étoile Funéraire Inc.  "
    assert value.normalized_value == "Étoile Funéraire Inc."
    assert value.normalizer_name == "business_name"
    assert value.normalizer_version == "1"
    assert value.normalized_at == "2026-08-08T12:00:00+00:00"
    assert value.warnings == ("trimmed surrounding whitespace",)


def test_as_record_serializes_warnings_deterministically() -> None:
    value = NormalizedValue(
        source_record_id=1,
        field_name="phone",
        original_value="403 555 0100",
        normalized_value="+14035550100",
        normalizer_name="phone",
        normalizer_version="1",
        normalized_at="2026-08-08T12:00:00+00:00",
        warnings=("country code inferred", "punctuation removed"),
    )

    record = value.as_record()

    assert json.loads(record["warnings"]) == [
        "country code inferred",
        "punctuation removed",
    ]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"source_record_id": 0}, "source_record_id"),
        ({"field_name": " "}, "field_name"),
        ({"normalizer_name": ""}, "normalizer_name"),
        ({"normalizer_version": ""}, "normalizer_version"),
        ({"normalized_at": ""}, "normalized_at"),
        ({"warnings": ("",)}, "warnings"),
    ],
)
def test_normalized_value_validation(kwargs: dict[str, object], message: str) -> None:
    values: dict[str, object] = {
        "source_record_id": 1,
        "field_name": "city",
        "original_value": "Calgary",
        "normalized_value": "Calgary",
        "normalizer_name": "city",
        "normalizer_version": "1",
        "normalized_at": "2026-08-08T12:00:00+00:00",
        "warnings": (),
    }
    values.update(kwargs)

    with pytest.raises(NormalizationError, match=message):
        NormalizedValue(**values).validate()


def test_make_normalized_value_generates_timestamp() -> None:
    value = make_normalized_value(
        source_record_id=1,
        field_name="province",
        original_value="Alberta",
        normalized_value="AB",
        normalizer_name="province",
        normalizer_version="1",
    )

    assert value.normalized_at
    assert "+00:00" in value.normalized_at
