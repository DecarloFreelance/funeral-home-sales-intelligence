from __future__ import annotations

import pytest

from canada_funeral_intel.deduplication.deterministic import (
    DeterministicMatchingError,
    evaluate_deterministic_signals,
)
from canada_funeral_intel.deduplication.models import MatchDecision


def test_exact_address_and_postal_code_requires_review() -> None:
    result = evaluate_deterministic_signals(
        10,
        {
            "address": "123 main street southwest",
            "postal_code": "T2P 1J9",
        },
        11,
        {
            "address": "123 main street southwest",
            "postal_code": "T2P 1J9",
        },
    )

    assert result is not None
    assert result.score == 0.99
    assert result.decision is MatchDecision.REVIEW
    assert "exact_address_postal" in result.matched_rules
    assert result.matched_signals == ("address", "postal_code")


def test_exact_phone_and_postal_code_is_automatic_match() -> None:
    result = evaluate_deterministic_signals(
        1,
        {"phone": "+14035550100", "postal_code": "T2P 1J9"},
        2,
        {"phone": "+14035550100", "postal_code": "T2P 1J9"},
    )

    assert result is not None
    assert result.score == 1.0
    assert result.decision is MatchDecision.MATCH


def test_exact_business_name_and_postal_code_is_automatic_match() -> None:
    result = evaluate_deterministic_signals(
        1,
        {
            "business_name": "funeral home etoile",
            "postal_code": "H2X 1Y4",
        },
        2,
        {
            "business_name": "funeral home etoile",
            "postal_code": "H2X 1Y4",
        },
    )

    assert result is not None
    assert result.score == 0.98
    assert result.decision is MatchDecision.MATCH


def test_phone_only_requires_review() -> None:
    result = evaluate_deterministic_signals(
        1,
        {"phone": "+14035550100"},
        2,
        {"phone": "+14035550100"},
    )

    assert result is not None
    assert result.score == 0.90
    assert result.decision is MatchDecision.REVIEW
    assert result.matched_rules == ("exact_phone",)


def test_shared_domain_and_city_requires_review() -> None:
    result = evaluate_deterministic_signals(
        1,
        {"domain": "example.ca", "city": "Calgary"},
        2,
        {"domain": "example.ca", "city": "Calgary"},
    )

    assert result is not None
    assert result.score == 0.88
    assert result.decision is MatchDecision.REVIEW


def test_name_city_province_requires_review_without_stronger_signal() -> None:
    result = evaluate_deterministic_signals(
        1,
        {
            "business_name": "north star funeral home",
            "city": "Calgary",
            "province": "AB",
        },
        2,
        {
            "business_name": "north star funeral home",
            "city": "Calgary",
            "province": "AB",
        },
    )

    assert result is not None
    assert result.score == 0.86
    assert result.decision is MatchDecision.REVIEW


def test_conflicting_records_do_not_match() -> None:
    result = evaluate_deterministic_signals(
        1,
        {"phone": "+14035550100", "postal_code": "T2P 1J9"},
        2,
        {"phone": "+14035550199", "postal_code": "V6B 1A1"},
    )

    assert result is None


def test_source_record_ids_are_canonicalized() -> None:
    result = evaluate_deterministic_signals(
        9,
        {"phone": "+14035550100"},
        3,
        {"phone": "+14035550100"},
    )

    assert result is not None
    assert result.left_source_record_id == 3
    assert result.right_source_record_id == 9


@pytest.mark.parametrize(
    ("left_id", "right_id", "message"),
    [
        (1, 1, "distinct"),
        (0, 1, "positive"),
    ],
)
def test_invalid_source_record_ids_are_rejected(
    left_id: int,
    right_id: int,
    message: str,
) -> None:
    with pytest.raises(DeterministicMatchingError, match=message):
        evaluate_deterministic_signals(
            left_id,
            {"phone": "+14035550100"},
            right_id,
            {"phone": "+14035550100"},
        )


def test_shared_address_postal_with_different_names_does_not_auto_match() -> None:
    result = evaluate_deterministic_signals(
        722,
        {
            "business_name": "scotia cremation centre",
            "address": "85 sackville cross road",
            "city": "LOWER SACKVILLE",
            "province": "NS",
            "postal_code": "B4C 2M2",
        },
        733,
        {
            "business_name": "t k barnard funeral home",
            "address": "85 sackville cross road",
            "city": "LOWER SACKVILLE",
            "province": "NS",
            "postal_code": "B4C 2M2",
        },
    )

    assert result is not None
    assert result.score == 0.99
    assert result.decision is MatchDecision.REVIEW
    assert "exact_address_postal" in result.matched_rules
    assert "exact_business_name_postal" not in result.matched_rules
