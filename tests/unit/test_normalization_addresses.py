from __future__ import annotations

import pytest

from canada_funeral_intel.normalization.addresses import (
    AddressNormalization,
    normalize_address,
)


def test_address_preserves_none() -> None:
    assert normalize_address(None) == AddressNormalization(
        display_address=None,
        comparison_key=None,
    )


def test_address_preserves_display_value() -> None:
    result = normalize_address("  123   Main St. SW  ")
    assert result.display_address == "123 Main St. SW"
    assert "whitespace normalized" in result.warnings


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("123 Main Street", "123 main street"),
        ("123 Main St.", "123 main street"),
        ("123 Main Ave", "123 main avenue"),
        ("123 Main Blvd.", "123 main boulevard"),
        ("123 Main Rd", "123 main road"),
        ("123 Main Dr.", "123 main drive"),
        ("123 Main Hwy", "123 main highway"),
        ("123 Main Cres.", "123 main crescent"),
        ("123 Main Pkwy", "123 main parkway"),
    ],
)
def test_english_street_types_are_canonicalized(
    value: str,
    expected: str,
) -> None:
    assert normalize_address(value).comparison_key == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("123 rue Sainte-Catherine", "123 rue sainte catherine"),
        ("123 chemin Sainte-Foy", "123 chemin sainte foy"),
        ("123 ch Sainte-Foy", "123 chemin sainte foy"),
        ("123 rang Saint-Pierre", "123 rang saint pierre"),
        ("123 montée Paiement", "123 montee paiement"),
    ],
)
def test_french_street_types_are_preserved_or_canonicalized(
    value: str,
    expected: str,
) -> None:
    assert normalize_address(value).comparison_key == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("123 Main St SW", "123 main street southwest"),
        ("123 Main Street South West", "123 main street south west"),
        ("123 rue Principale Ouest", "123 rue principale west"),
        ("123 rue Principale Est", "123 rue principale east"),
        ("123 Main St NE", "123 main street northeast"),
    ],
)
def test_directions_are_canonicalized(value: str, expected: str) -> None:
    assert normalize_address(value).comparison_key == expected


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        ("Unit 4 123 Main St", "4", "123 main street unit 4"),
        ("Suite 205, 123 Main St", "205", "123 main street unit 205"),
        ("Ste 205 123 Main St", "205", "123 main street unit 205"),
        ("Appartement 3 10 rue Laval", "3", "10 rue laval unit 3"),
        ("#7 123 Main St", "7", "123 main street unit 7"),
        ("123 Main St, Unit 4", "4", "123 main street unit 4"),
    ],
)
def test_unit_designators_are_normalized(
    value: str,
    unit: str,
    expected: str,
) -> None:
    result = normalize_address(value)
    assert result.unit == unit
    assert result.comparison_key == expected
    assert "address unit normalized" in result.warnings


def test_address_comparison_is_accent_insensitive() -> None:
    accented = normalize_address("123 montée Paiement")
    plain = normalize_address("123 Montee Paiement")
    assert accented.comparison_key == plain.comparison_key


def test_address_comparison_is_punctuation_insensitive() -> None:
    left = normalize_address("123 St-Joseph St.")
    right = normalize_address("123 St Joseph Street")
    assert left.comparison_key == right.comparison_key


def test_address_does_not_guess_missing_civic_information() -> None:
    result = normalize_address("Main Street")
    assert result.display_address == "Main Street"
    assert result.comparison_key == "main street"


def test_address_does_not_reorder_number_or_street_name() -> None:
    result = normalize_address("Main Street 123")
    assert result.comparison_key == "main street 123"


def test_address_keeps_po_box_as_text() -> None:
    result = normalize_address("PO Box 123")
    assert result.display_address == "PO Box 123"
    assert result.comparison_key == "po box 123"


def test_empty_address_becomes_none() -> None:
    result = normalize_address("   ")
    assert result.display_address is None
    assert result.comparison_key is None
    assert "empty value" in result.warnings


def test_address_warns_when_comparison_key_changes() -> None:
    result = normalize_address("123 Main St.")
    assert "address comparison key canonicalized" in result.warnings


def test_already_canonical_address_has_no_canonicalization_warning() -> None:
    result = normalize_address("123 main street")
    assert "address comparison key canonicalized" not in result.warnings
