from __future__ import annotations

import pytest

from canada_funeral_intel.deduplication.fuzzy import (
    FuzzyMatchingError,
    evaluate_fuzzy_signals,
    text_similarity,
)
from canada_funeral_intel.deduplication.models import EvidenceKind, MatchDecision


def test_text_similarity_handles_small_name_variation() -> None:
    assert text_similarity("smith funeral home", "smiths funeral home") > 0.95


def test_text_similarity_handles_reordered_tokens() -> None:
    assert text_similarity("funeral home etoile", "etoile funeral home") == 1.0


def test_similar_name_same_city_and_province_is_review_candidate() -> None:
    result = evaluate_fuzzy_signals(
        1,
        {
            "business_name": "smith funeral home",
            "city": "Calgary",
            "province": "AB",
        },
        2,
        {
            "business_name": "smiths funeral home",
            "city": "Calgary",
            "province": "AB",
        },
    )

    assert result is not None
    assert result.score > 0.95
    assert result.decision is MatchDecision.REVIEW
    assert result.left_source_record_id == 1
    assert result.right_source_record_id == 2


def test_similar_address_with_matching_postal_is_review_candidate() -> None:
    result = evaluate_fuzzy_signals(
        1,
        {
            "address": "123 main street southwest",
            "postal_code": "T2P 1J9",
        },
        2,
        {
            "address": "123 main street sw",
            "postal_code": "T2P 1J9",
        },
    )

    assert result is not None
    assert result.score > 0.85
    assert result.decision is MatchDecision.REVIEW


def test_conflicting_context_lowers_weighted_score() -> None:
    result = evaluate_fuzzy_signals(
        1,
        {
            "business_name": "smith funeral home",
            "city": "Calgary",
            "postal_code": "T2P 1J9",
            "province": "AB",
        },
        2,
        {
            "business_name": "smiths funeral home",
            "city": "Edmonton",
            "postal_code": "T5J 0N3",
            "province": "AB",
        },
    )

    assert result is None


def test_requires_a_core_name_or_address_signal() -> None:
    result = evaluate_fuzzy_signals(
        1,
        {"city": "Calgary", "province": "AB"},
        2,
        {"city": "Calgary", "province": "AB"},
    )
    assert result is None


def test_weak_core_similarity_is_rejected() -> None:
    result = evaluate_fuzzy_signals(
        1,
        {
            "business_name": "alpha funeral home",
            "city": "Calgary",
            "province": "AB",
        },
        2,
        {
            "business_name": "completely unrelated memorial",
            "city": "Calgary",
            "province": "AB",
        },
    )
    assert result is None


def test_evidence_is_weighted_and_typed() -> None:
    result = evaluate_fuzzy_signals(
        1,
        {
            "business_name": "smith funeral home",
            "city": "Calgary",
            "province": "AB",
        },
        2,
        {
            "business_name": "smiths funeral home",
            "city": "Calgary",
            "province": "AB",
        },
    )

    assert result is not None
    evidence = {item.signal_name: item for item in result.evidence}
    assert evidence["business_name"].evidence_kind is EvidenceKind.FUZZY
    assert evidence["business_name"].weight == 0.40
    assert 0.0 < evidence["business_name"].contribution <= 0.40
    assert evidence["city"].evidence_kind is EvidenceKind.CONTEXT
    assert evidence["city"].contribution == 0.10


def test_source_record_ids_are_canonicalized_with_values() -> None:
    result = evaluate_fuzzy_signals(
        9,
        {"business_name": "smith funeral home", "city": "Calgary"},
        3,
        {"business_name": "smiths funeral home", "city": "Calgary"},
    )

    assert result is not None
    assert result.left_source_record_id == 3
    assert result.right_source_record_id == 9
    evidence = {item.signal_name: item for item in result.evidence}
    assert evidence["business_name"].left_value == "smiths funeral home"
    assert evidence["business_name"].right_value == "smith funeral home"


@pytest.mark.parametrize(
    ("left_id", "right_id", "message"),
    [
        (1, 1, "distinct"),
        (0, 1, "positive"),
        (1, 0, "positive"),
    ],
)
def test_invalid_source_record_ids_are_rejected(
    left_id: int,
    right_id: int,
    message: str,
) -> None:
    with pytest.raises(FuzzyMatchingError, match=message):
        evaluate_fuzzy_signals(
            left_id,
            {"business_name": "smith funeral home"},
            right_id,
            {"business_name": "smiths funeral home"},
        )
