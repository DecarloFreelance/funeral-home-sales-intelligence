from __future__ import annotations

import json

import pytest

from canada_funeral_intel.collectors.manitoba import (
    ManitobaCollectorError,
    parse_funeral_homes,
    records_as_parse_result,
)


def sample_text() -> str:
    return """Licenced Funeral Homes for 2026

Funeral Home                                     Address                      City                    Phone          Email

Alpha Funeral Home                               1 Main Street                Winnipeg                204-111-1111   alpha@example.com
Cropo Funeral & Cremation Services                                            Winnipeg
Cropo Funeral & Cremation Services                                            Winnipeg
Anderson Family Funeral Home                     9 Railway Avenue             Ashern                  204-768-3606   andersonfamilyfuneralhome@gmail.co
                                                                                                                      m

Total Licenced Funeral Homes for 2026: 4
"""


def test_parser_preserves_missing_and_duplicate_source_rows() -> None:
    records = parse_funeral_homes(sample_text())

    assert len(records) == 4
    assert records[1].name == "Cropo Funeral & Cremation Services"
    assert records[2].name == "Cropo Funeral & Cremation Services"
    assert records[1].address is None
    assert records[1].phone is None
    assert records[1].email is None
    assert records[3].email == "andersonfamilyfuneralhome@gmail.com"


def test_parse_result_has_stable_unique_source_ids() -> None:
    parsed = records_as_parse_result(parse_funeral_homes(sample_text()))

    assert [row.external_record_id for row in parsed.rows] == [
        "MB-2026-001",
        "MB-2026-002",
        "MB-2026-003",
        "MB-2026-004",
    ]
    assert len({row.checksum for row in parsed.rows}) >= 3
    assert json.loads(parsed.rows[1].raw_payload)["address"] is None


def test_declared_count_mismatch_fails_closed() -> None:
    with pytest.raises(ManitobaCollectorError, match="row count"):
        parse_funeral_homes(
            sample_text().replace(
                "Total Licenced Funeral Homes for 2026: 4",
                "Total Licenced Funeral Homes for 2026: 5",
            )
        )
