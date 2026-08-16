from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations

from canada_funeral_intel.deduplication.models import MatchDecision
from canada_funeral_intel.storage.database import transaction


class DeterministicMatchingError(RuntimeError):
    """Raised when deterministic entity matching cannot complete safely."""


@dataclass(frozen=True, slots=True)
class DeterministicRule:
    name: str
    fields: tuple[str, ...]
    score: float
    decision: MatchDecision


@dataclass(frozen=True, slots=True)
class DeterministicEvaluation:
    left_source_record_id: int
    right_source_record_id: int
    matched_rules: tuple[str, ...]
    matched_signals: tuple[str, ...]
    score: float
    decision: MatchDecision


@dataclass(frozen=True, slots=True)
class DeterministicMatchRun:
    records_seen: int
    pairs_found: int
    candidates_inserted: int
    candidates_unchanged: int
    evidence_inserted: int


_RULES = (
    DeterministicRule(
        name="exact_phone_postal",
        fields=("phone", "postal_code"),
        score=1.00,
        decision=MatchDecision.MATCH,
    ),
    DeterministicRule(
        name="exact_address_postal",
        fields=("address", "postal_code"),
        score=0.99,
        decision=MatchDecision.REVIEW,
    ),
    DeterministicRule(
        name="exact_business_name_postal",
        fields=("business_name", "postal_code"),
        score=0.98,
        decision=MatchDecision.MATCH,
    ),
    DeterministicRule(
        name="exact_phone",
        fields=("phone",),
        score=0.90,
        decision=MatchDecision.REVIEW,
    ),
    DeterministicRule(
        name="exact_domain_city",
        fields=("domain", "city"),
        score=0.88,
        decision=MatchDecision.REVIEW,
    ),
    DeterministicRule(
        name="exact_business_name_parent_organization_city",
        fields=("business_name", "parent_organization", "city"),
        score=0.92,
        decision=MatchDecision.REVIEW,
    ),
    DeterministicRule(
        name="exact_business_name_city_province",
        fields=("business_name", "city", "province"),
        score=0.86,
        decision=MatchDecision.REVIEW,
    ),
)

_CANDIDATE_METHOD = "deterministic_v1"


def _has_conflicting_parent_organization(
    left: dict[str, str],
    right: dict[str, str],
) -> bool:
    left_parent = left.get("parent_organization")
    right_parent = right.get("parent_organization")

    return (
        left_parent is not None
        and right_parent is not None
        and left_parent != right_parent
    )


def evaluate_deterministic_signals(
    left_source_record_id: int,
    left: dict[str, str],
    right_source_record_id: int,
    right: dict[str, str],
) -> DeterministicEvaluation | None:
    if left_source_record_id == right_source_record_id:
        raise DeterministicMatchingError("source record IDs must be distinct")

    if _has_conflicting_parent_organization(left, right):
        return None

    left_id, right_id = sorted((left_source_record_id, right_source_record_id))
    if left_id < 1:
        raise DeterministicMatchingError("source record IDs must be positive integers")

    matched = tuple(
        rule
        for rule in _RULES
        if all(
            left.get(field) is not None and left.get(field) == right.get(field)
            for field in rule.fields
        )
    )
    if not matched:
        return None

    matched_signals = tuple(
        dict.fromkeys(field for rule in matched for field in rule.fields)
    )
    score = max(rule.score for rule in matched)
    decision = (
        MatchDecision.MATCH
        if any(rule.decision is MatchDecision.MATCH for rule in matched)
        else MatchDecision.REVIEW
    )

    return DeterministicEvaluation(
        left_source_record_id=left_id,
        right_source_record_id=right_id,
        matched_rules=tuple(rule.name for rule in matched),
        matched_signals=matched_signals,
        score=score,
        decision=decision,
    )


def generate_deterministic_matches(
    connection: sqlite3.Connection,
) -> DeterministicMatchRun:
    signals = _load_latest_normalized_signals(connection)
    evaluations = _candidate_evaluations(signals)

    inserted = 0
    unchanged = 0
    evidence_inserted = 0

    try:
        with transaction(connection):
            for evaluation in evaluations:
                candidate_id, was_inserted = _persist_candidate(
                    connection,
                    evaluation,
                )
                if was_inserted:
                    inserted += 1
                else:
                    unchanged += 1

                evidence_inserted += _persist_evidence(
                    connection,
                    candidate_id,
                    evaluation,
                    signals,
                )
    except sqlite3.Error as exc:
        raise DeterministicMatchingError(
            f"Deterministic matching database operation failed: {exc}"
        ) from exc

    return DeterministicMatchRun(
        records_seen=len(signals),
        pairs_found=len(evaluations),
        candidates_inserted=inserted,
        candidates_unchanged=unchanged,
        evidence_inserted=evidence_inserted,
    )


def _load_latest_normalized_signals(
    connection: sqlite3.Connection,
) -> dict[int, dict[str, str]]:
    rows = connection.execute(
        """
        SELECT nv.source_record_id, nv.field_name, nv.normalized_value
        FROM normalized_values AS nv
        JOIN (
            SELECT source_record_id, field_name, MAX(id) AS normalized_value_id
            FROM normalized_values
            GROUP BY source_record_id, field_name
        ) AS latest
          ON latest.normalized_value_id = nv.id
        WHERE nv.normalized_value IS NOT NULL
        ORDER BY nv.source_record_id, nv.field_name
        """
    ).fetchall()

    signals: dict[int, dict[str, str]] = defaultdict(dict)
    for row in rows:
        signals[int(row["source_record_id"])][str(row["field_name"])] = str(
            row["normalized_value"]
        )
    return dict(signals)


def _candidate_evaluations(
    signals: dict[int, dict[str, str]],
) -> list[DeterministicEvaluation]:
    candidate_pairs: set[tuple[int, int]] = set()

    for rule in _RULES:
        groups: dict[tuple[str, ...], list[int]] = defaultdict(list)
        for source_record_id, values in signals.items():
            key_values = tuple(values.get(field) for field in rule.fields)
            if any(value is None for value in key_values):
                continue
            groups[tuple(str(value) for value in key_values)].append(source_record_id)

        for grouped_ids in groups.values():
            for left_id, right_id in combinations(sorted(set(grouped_ids)), 2):
                candidate_pairs.add((left_id, right_id))

    evaluations: list[DeterministicEvaluation] = []
    for left_id, right_id in sorted(candidate_pairs):
        evaluation = evaluate_deterministic_signals(
            left_id,
            signals[left_id],
            right_id,
            signals[right_id],
        )
        if evaluation is not None:
            evaluations.append(evaluation)
    return evaluations


def _persist_candidate(
    connection: sqlite3.Connection,
    evaluation: DeterministicEvaluation,
) -> tuple[int, bool]:
    row = connection.execute(
        """
        SELECT id
        FROM match_candidates
        WHERE left_source_record_id = ?
          AND right_source_record_id = ?
          AND candidate_method = ?
        """,
        (
            evaluation.left_source_record_id,
            evaluation.right_source_record_id,
            _CANDIDATE_METHOD,
        ),
    ).fetchone()
    if row is not None:
        return int(row["id"]), False

    cursor = connection.execute(
        """
        INSERT INTO match_candidates (
            left_source_record_id,
            right_source_record_id,
            candidate_method,
            score,
            decision
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            evaluation.left_source_record_id,
            evaluation.right_source_record_id,
            _CANDIDATE_METHOD,
            evaluation.score,
            evaluation.decision.value,
        ),
    )
    if cursor.lastrowid is None:
        raise DeterministicMatchingError("Match candidate insert returned no row ID")
    return int(cursor.lastrowid), True


def _persist_evidence(
    connection: sqlite3.Connection,
    candidate_id: int,
    evaluation: DeterministicEvaluation,
    signals: dict[int, dict[str, str]],
) -> int:
    inserted = 0
    left = signals[evaluation.left_source_record_id]
    right = signals[evaluation.right_source_record_id]

    for signal_name in evaluation.matched_signals:
        left_value = left[signal_name]
        right_value = right[signal_name]
        exists = connection.execute(
            """
            SELECT 1
            FROM match_evidence
            WHERE match_candidate_id = ?
              AND signal_name = ?
              AND left_value = ?
              AND right_value = ?
              AND evidence_kind = 'deterministic'
            LIMIT 1
            """,
            (
                candidate_id,
                signal_name,
                left_value,
                right_value,
            ),
        ).fetchone()
        if exists is not None:
            continue

        connection.execute(
            """
            INSERT INTO match_evidence (
                match_candidate_id,
                signal_name,
                left_value,
                right_value,
                contribution,
                evidence_kind
            )
            VALUES (?, ?, ?, ?, ?, 'deterministic')
            """,
            (
                candidate_id,
                signal_name,
                left_value,
                right_value,
                1.0,
            ),
        )
        inserted += 1

    return inserted
