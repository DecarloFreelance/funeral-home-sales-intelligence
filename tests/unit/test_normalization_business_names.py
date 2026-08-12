from __future__ import annotations

import pytest

from canada_funeral_intel.normalization.business_names import (
    BusinessNameNormalization,
    normalize_business_name,
)


def test_business_name_preserves_display_name() -> None:
    result = normalize_business_name("  Maison funéraire Étoile Inc.  ")

    assert result.display_name == "Maison funéraire Étoile Inc."
    assert "whitespace normalized" in result.warnings


def test_business_name_preserves_none() -> None:
    assert normalize_business_name(None) == BusinessNameNormalization(
        display_name=None,
        comparison_key=None,
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Maison funéraire Étoile Inc.", "funeral home etoile"),
        ("Salon Funéraire Beaulieu Ltée", "funeral home beaulieu ltee"),
        ("Étoile Funeral Home Ltd.", "etoile funeral home"),
        ("North Star Funeral Chapel Inc", "north star funeral chapel"),
        ("Centre de crémation Laval", "cremation centre laval"),
        ("Laval Cremation Center", "laval cremation centre"),
        ("Crématorium du Québec", "crematorium du quebec"),
        ("Harbour Mortuaries Ltd", "harbour mortuary"),
    ],
)
def test_business_name_comparison_key(
    value: str,
    expected: str,
) -> None:
    assert normalize_business_name(value).comparison_key == expected


@pytest.mark.parametrize(
    ("value", "term"),
    [
        ("Maison funéraire Étoile", "funeral home"),
        ("North Star Funeral Chapel", "funeral chapel"),
        ("Centre de crémation Laval", "cremation centre"),
        ("Crématorium du Québec", "crematorium"),
        ("Harbour Mortuary", "mortuary"),
        ("Evergreen Memorial Services", "memorial"),
    ],
)
def test_business_name_detects_terminology(value: str, term: str) -> None:
    assert term in normalize_business_name(value).terminology


def test_business_name_removes_only_trailing_legal_suffixes() -> None:
    result = normalize_business_name("ABC Corporation Funeral Home Inc.")

    assert result.comparison_key == "abc corporation funeral home"


def test_business_name_does_not_translate_arbitrary_words() -> None:
    result = normalize_business_name("Maison du Souvenir")

    assert result.display_name == "Maison du Souvenir"
    assert result.comparison_key == "maison du souvenir"
    assert result.terminology == ()


def test_business_name_comparison_is_accent_insensitive() -> None:
    accented = normalize_business_name("Services Commémoratifs Étoile")
    plain = normalize_business_name("Services Commemoratifs Etoile")

    assert accented.comparison_key == plain.comparison_key


def test_business_name_comparison_is_punctuation_insensitive() -> None:
    left = normalize_business_name("Smith & Jones Funeral Home")
    right = normalize_business_name("Smith-Jones Funeral Home")

    assert left.comparison_key == right.comparison_key


def test_business_name_warns_when_comparison_key_is_canonicalized() -> None:
    result = normalize_business_name("Maison funéraire Étoile Inc.")

    assert "business name comparison key canonicalized" in result.warnings
