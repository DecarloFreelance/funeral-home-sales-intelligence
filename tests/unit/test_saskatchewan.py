from __future__ import annotations

import json

import pytest

from canada_funeral_intel.collectors.saskatchewan import (
    SaskatchewanCollectorError,
    parse_roster,
    records_as_parse_result,
)


def sample_text() -> str:
    left = f"{'Alpha Funeral Home':<49} {'FH':<6}{'7500':<7}{'Regina':<22}"
    right = f"{'Beta Cremation Centre':<55} {'FHC':<6}{'7501':<7}{'Saskatoon'}"
    return (
        "FUNERAL HOMES, CREMATORIUMS, TRANSFER SERVICES\n"
        f"{left}{right}\n"
        f"{'Only Crematorium':<49} {'C':<6}{'7502':<7}{'Moose Jaw':<22}\n"
        "FUNERAL HOME LICENSES CANCELLED\n"
    )


def test_parse_roster_selects_funeral_home_license_codes() -> None:
    records = parse_roster(sample_text())

    assert [record.external_record_id for record in records] == ["SK-7500", "SK-7501"]
    assert records[0].city == "Regina"
    assert records[1].license_code == "FHC"


def test_parse_result_preserves_source_payload() -> None:
    parsed = records_as_parse_result(parse_roster(sample_text()))

    assert parsed.records_seen == 2
    assert json.loads(parsed.rows[0].raw_payload)["province"] == "SK"
    assert len(parsed.rows[0].checksum) == 64


def test_parse_roster_fails_without_business_section() -> None:
    with pytest.raises(SaskatchewanCollectorError, match="section"):
        parse_roster("not a roster")
