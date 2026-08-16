from __future__ import annotations

import json

import pytest

from canada_funeral_intel.collectors.newfoundland import (
    NewfoundlandCollectorError,
    parse_directory,
    records_as_parse_result,
)


def sample_html() -> str:
    return """
    <p>Example Funeral Home</p>
    <p>10 Main Street</p>
    <p>St. John's, NL A1A 1A1</p>
    <p>Phone: (709) 555-0100</p>
    <p>E-mail: example@example.ca</p>
    <p>Another Funeral Home</p>
    <p>20 King Street</p>
    <p>Corner Brook, NL A2H 2B2</p>
    <p>Phone: (709) 555-0200</p>
    """


def test_parse_directory_extracts_named_addresses() -> None:
    records = parse_directory(sample_html())

    assert len(records) == 2
    assert records[0].name == "Example Funeral Home"
    assert records[0].city == "St. John's"
    assert records[1].city == "Corner Brook"


def test_parse_result_preserves_province_and_stable_id() -> None:
    parsed = records_as_parse_result(parse_directory(sample_html()))

    payload = json.loads(parsed.rows[0].raw_payload)
    assert payload["province"] == "NL"
    assert parsed.rows[0].external_record_id.startswith("NL-")


def test_parse_directory_fails_without_addresses() -> None:
    with pytest.raises(NewfoundlandCollectorError, match="no funeral homes"):
        parse_directory("<p>Example Funeral Home</p>")
