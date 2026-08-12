from __future__ import annotations

import pytest

from canada_funeral_intel.deduplication.models import (
    EntityResolutionError,
    EvidenceKind,
    MatchCandidate,
    MatchDecision,
    MatchEvidence,
    MergeDecision,
)


def test_match_candidate_accepts_ordered_pair() -> None:
    candidate = MatchCandidate(
        left_source_record_id=10,
        right_source_record_id=11,
        candidate_method="exact_phone",
        score=1.0,
    )
    candidate.validate()
    assert candidate.decision is MatchDecision.PENDING


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"left_source_record_id": 0}, "left_source_record_id"),
        ({"right_source_record_id": 0}, "right_source_record_id"),
        (
            {"left_source_record_id": 11, "right_source_record_id": 10},
            "ordered and distinct",
        ),
        ({"candidate_method": " "}, "candidate_method"),
        ({"score": -0.1}, "score"),
        ({"score": 1.1}, "score"),
    ],
)
def test_match_candidate_validation(
    kwargs: dict[str, object],
    message: str,
) -> None:
    values: dict[str, object] = {
        "left_source_record_id": 10,
        "right_source_record_id": 11,
        "candidate_method": "normalized_signal",
        "score": 0.75,
    }
    values.update(kwargs)
    with pytest.raises(EntityResolutionError, match=message):
        MatchCandidate(**values).validate()


def test_match_evidence_supports_positive_and_negative_contributions() -> None:
    positive = MatchEvidence(
        signal_name="phone",
        left_value="+14035550100",
        right_value="+14035550100",
        contribution=1.0,
        evidence_kind=EvidenceKind.DETERMINISTIC,
    )
    negative = MatchEvidence(
        signal_name="postal_code",
        left_value="T2P 1J9",
        right_value="V6B 1A1",
        contribution=-0.5,
        evidence_kind=EvidenceKind.CONTEXT,
    )
    positive.validate()
    negative.validate()


@pytest.mark.parametrize("contribution", [-1.1, 1.1])
def test_match_evidence_rejects_invalid_contribution(
    contribution: float,
) -> None:
    with pytest.raises(EntityResolutionError, match="contribution"):
        MatchEvidence(
            signal_name="domain",
            left_value="example.ca",
            right_value="example.ca",
            contribution=contribution,
            evidence_kind=EvidenceKind.FUZZY,
        ).validate()


def test_merge_decision_requires_distinct_entities() -> None:
    decision = MergeDecision(
        survivor_entity_id=1,
        merged_entity_id=2,
        decision_source="manual_review",
        reason="same branch confirmed",
    )
    decision.validate()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"survivor_entity_id": 0}, "positive"),
        ({"merged_entity_id": 0}, "positive"),
        ({"merged_entity_id": 1}, "distinct"),
        ({"decision_source": ""}, "decision_source"),
        ({"reason": ""}, "reason"),
    ],
)
def test_merge_decision_validation(
    kwargs: dict[str, object],
    message: str,
) -> None:
    values: dict[str, object] = {
        "survivor_entity_id": 1,
        "merged_entity_id": 2,
        "decision_source": "automatic",
        "reason": "deterministic match",
    }
    values.update(kwargs)
    with pytest.raises(EntityResolutionError, match=message):
        MergeDecision(**values).validate()
