from __future__ import annotations

import pytest

from canada_funeral_intel.normalization.scalars import (
    ScalarNormalization,
    normalize_city,
    normalize_domain,
    normalize_email,
    normalize_phone,
    normalize_postal_code,
    normalize_province,
    normalize_text,
    normalize_url,
)


def test_normalize_text_collapses_whitespace() -> None:
    result = normalize_text("  Maison   funéraire\tÉtoile  ")
    assert result.value == "Maison funéraire Étoile"
    assert result.warnings == ("whitespace normalized",)


def test_normalize_text_preserves_none() -> None:
    assert normalize_text(None) == ScalarNormalization(None)


def test_normalize_city_is_conservative_text_cleanup() -> None:
    result = normalize_city("  Trois-Rivières  ")
    assert result.value == "Trois-Rivières"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Alberta", "AB"),
        ("ab", "AB"),
        ("Québec", "QC"),
        ("PQ", "QC"),
        ("British Columbia", "BC"),
        ("Colombie-Britannique", "BC"),
        ("Prince Edward Island", "PE"),
        ("Île-du-Prince-Édouard", "PE"),
        ("Northwest Territories", "NT"),
        ("Territoires du Nord-Ouest", "NT"),
    ],
)
def test_normalize_province_known_values(value: str, expected: str) -> None:
    assert normalize_province(value).value == expected


def test_normalize_province_rejects_unknown_value() -> None:
    result = normalize_province("Atlantis")
    assert result.value is None
    assert "unrecognized Canadian province or territory" in result.warnings


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("T2P1J9", "T2P 1J9"),
        ("t2p 1j9", "T2P 1J9"),
        ("T2P-1J9", "T2P 1J9"),
    ],
)
def test_normalize_postal_code(value: str, expected: str) -> None:
    assert normalize_postal_code(value).value == expected


def test_normalize_postal_code_rejects_invalid_value() -> None:
    result = normalize_postal_code("12345")
    assert result.value is None
    assert "invalid Canadian postal code" in result.warnings


def test_normalize_email_lowercases_address() -> None:
    result = normalize_email(" Info@Example.CA ")
    assert result.value == "info@example.ca"
    assert "email lowercased" in result.warnings


def test_normalize_email_rejects_invalid_address() -> None:
    assert normalize_email("not-an-email").value is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("403-555-0100", "+14035550100"),
        ("+1 (403) 555-0100", "+14035550100"),
        ("403 555 0100 ext 42", "+14035550100 x42"),
        ("204-982-7550 x. 1", "+12049827550 x1"),
    ],
)
def test_normalize_phone(value: str, expected: str) -> None:
    assert normalize_phone(value).value == expected


def test_normalize_phone_rejects_wrong_length() -> None:
    result = normalize_phone("555-0100")
    assert result.value is None
    assert "invalid North American phone number" in result.warnings


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("example.ca", "https://example.ca/"),
        ("HTTP://Example.CA", "http://example.ca/"),
        ("https://example.ca/contact#staff", "https://example.ca/contact"),
    ],
)
def test_normalize_url(value: str, expected: str) -> None:
    assert normalize_url(value).value == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("www.Example.ca", "example.ca"),
        ("https://www.example.ca/contact", "example.ca"),
        ("sub.example.ca", "sub.example.ca"),
    ],
)
def test_normalize_domain(value: str, expected: str) -> None:
    assert normalize_domain(value).value == expected


def test_normalize_domain_rejects_single_label() -> None:
    result = normalize_domain("localhost")
    assert result.value is None
    assert "invalid domain" in result.warnings
