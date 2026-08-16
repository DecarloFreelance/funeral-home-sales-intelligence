from __future__ import annotations

import json

import pytest

from canada_funeral_intel.collectors.yukon import (
    YukonCollectorError,
    parse_directory,
    records_as_parse_result,
)


def test_parse_directory_extracts_heritage_north() -> None:
    records = parse_directory(
        "<h5>Heritage North Funeral Home</h5><p>1101 Centennial St<br>Whitehorse, Yukon, Y1A 3Z1</p>"
    )
    assert records[0].city == "Whitehorse"
    payload = json.loads(records_as_parse_result(records).rows[0].raw_payload)
    assert payload["province"] == "YT"


def test_parse_directory_requires_expected_address() -> None:
    with pytest.raises(YukonCollectorError, match="no funeral-home"):
        parse_directory("<h5>Other Funeral Home</h5><p>Whitehorse, Yukon</p>")
