from __future__ import annotations

from canada_funeral_intel.deduplication.deterministic import (
    evaluate_deterministic_signals,
)
from canada_funeral_intel.deduplication.fuzzy import evaluate_fuzzy_signals
from canada_funeral_intel.deduplication.models import MatchDecision
from canada_funeral_intel.normalization import execution as normalization_execution


def test_parent_organization_aliases_normalize_as_distinct_signal() -> None:
    aliases = {
        "parent_organization",
        "parent_organization_name",
        "parent_company",
        "parent_company_name",
    }

    for alias in aliases:
        assert normalization_execution._FIELD_ALIASES[alias] == "parent_organization"

    value = normalization_execution._normalize_field(
        source_record_id=1,
        field_name="parent_organization",
        original_value="  North Star Group Inc.  ",
    )

    assert value.field_name == "parent_organization"
    assert value.normalizer_name == "parent_organization"
    assert value.normalized_value == "north star group"


def test_deterministic_parent_organization_context_generates_branch_candidate() -> None:
    result = evaluate_deterministic_signals(
        1,
        {
            "business_name": "north star funeral home",
            "parent_organization": "north star group",
            "city": "calgary",
        },
        2,
        {
            "business_name": "north star funeral home",
            "parent_organization": "north star group",
            "city": "calgary",
        },
    )

    assert result is not None
    assert result.decision is MatchDecision.REVIEW
    assert "exact_business_name_parent_organization_city" in result.matched_rules
    assert "parent_organization" in result.matched_signals


def test_deterministic_conflicting_parent_organizations_are_rejected() -> None:
    result = evaluate_deterministic_signals(
        1,
        {
            "phone": "+14035550100",
            "postal_code": "T2P 1J9",
            "parent_organization": "north star group",
        },
        2,
        {
            "phone": "+14035550100",
            "postal_code": "T2P 1J9",
            "parent_organization": "prairie memorial group",
        },
    )

    assert result is None


def test_fuzzy_parent_organization_context_supports_branch_candidate() -> None:
    result = evaluate_fuzzy_signals(
        1,
        {
            "business_name": "smith funeral home",
            "parent_organization": "smith family services",
            "city": "calgary",
            "province": "AB",
        },
        2,
        {
            "business_name": "smiths funeral home",
            "parent_organization": "smith family services",
            "city": "calgary",
            "province": "AB",
        },
    )

    assert result is not None
    assert result.decision is MatchDecision.REVIEW
    evidence = {item.signal_name: item for item in result.evidence}
    assert evidence["parent_organization"].similarity == 1.0
    assert evidence["parent_organization"].contribution > 0.0


def test_fuzzy_conflicting_parent_organizations_are_rejected() -> None:
    result = evaluate_fuzzy_signals(
        1,
        {
            "business_name": "smith funeral home",
            "parent_organization": "smith family services",
            "city": "calgary",
            "province": "AB",
        },
        2,
        {
            "business_name": "smiths funeral home",
            "parent_organization": "prairie memorial group",
            "city": "calgary",
            "province": "AB",
        },
    )

    assert result is None
