from __future__ import annotations

import json

import pytest

from canada_funeral_intel.collectors.british_columbia import (
    BritishColumbiaCollectorError,
    parse_register,
    records_as_parse_result,
)


def sample_html() -> str:
    return """
    <html><body>
      <table class="cpbc-data-query-results">
        <thead><tr>
          <th>Licence type</th><th>Licence number</th><th>Business name</th>
          <th>Does business as</th><th>Address</th>
          <th>Initial issue date</th><th>Licence expiry date</th>
          <th>Licence status</th>
        </tr></thead>
        <tbody>
          <tr><td>Funeral Services</td><td>12345</td>
          <td>Example Holdings Ltd.</td><td>Example Funeral Home</td>
          <td>1 Main Street VICTORIA BC V8V1A1</td><td>2020-01-01</td>
          <td>2027-09-14</td><td>Issued</td></tr>
          <tr><td>Cemetery</td><td>99999</td><td>Excluded Cemetery</td>
          <td></td><td>2 Main Street VICTORIA BC V8V1A2</td><td></td>
          <td>2027-09-14</td><td>Issued</td></tr>
        </tbody>
      </table>
    </body></html>
    """


def test_parse_register_preserves_licence_and_trade_name() -> None:
    records = parse_register(sample_html())

    assert len(records) == 1
    assert records[0].external_record_id == "BC-12345"
    assert records[0].legal_name == "Example Holdings Ltd."
    assert records[0].trade_name == "Example Funeral Home"
    assert records[0].city == "Victoria"
    assert records[0].licence_status == "Issued"


def test_parse_result_has_stable_payload_and_checksum() -> None:
    parsed = records_as_parse_result(parse_register(sample_html()))

    assert parsed.records_seen == 1
    payload = json.loads(parsed.rows[0].raw_payload)
    assert payload["province"] == "BC"
    assert payload["licence_number"] == "12345"
    assert len(parsed.rows[0].checksum) == 64


def test_parse_register_fails_closed_without_expected_table() -> None:
    with pytest.raises(BritishColumbiaCollectorError, match="headers"):
        parse_register("<html><body>No table</body></html>")
