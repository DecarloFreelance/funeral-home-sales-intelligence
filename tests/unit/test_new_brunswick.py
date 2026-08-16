from __future__ import annotations

import json

import pytest

from canada_funeral_intel.collectors.new_brunswick import (
    NewBrunswickCollectorError,
    parse_directory,
    records_as_parse_result,
)


def sample_html() -> str:
    return """
    <h2>Example Funeral Home</h2>
    <div>Contact: Example Director</div>
    <h3>10 Main Street, Fredericton NB, E3B 1A1</h3>
    <h2>Another Funeral Home</h2>
    <h3>20 King Street Moncton NB E1C 1A1</h3>
    """


def test_parse_directory_extracts_named_member_addresses() -> None:
    records = parse_directory(sample_html())

    assert len(records) == 2
    assert records[0].name == "Example Funeral Home"
    assert records[0].city == "Fredericton"
    assert records[1].city == "Moncton"


def test_parse_result_preserves_province_and_stable_id() -> None:
    parsed = records_as_parse_result(parse_directory(sample_html()))

    payload = json.loads(parsed.rows[0].raw_payload)
    assert payload["province"] == "NB"
    assert parsed.rows[0].external_record_id.startswith("NB-")


def test_parse_directory_fails_without_addresses() -> None:
    with pytest.raises(NewBrunswickCollectorError, match="no member"):
        parse_directory("<h2>Example Funeral Home</h2>")
