from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from itertools import combinations

from canada_funeral_intel.deduplication.models import EvidenceKind, MatchDecision
from canada_funeral_intel.storage.database import transaction


class FuzzyMatchingError(RuntimeError):
    """Raised when fuzzy entity matching cannot complete safely."""


@dataclass(frozen=True, slots=True)
class FuzzySignal:
    name: str
    weight: float
    evidence_kind: EvidenceKind
    fuzzy: bool


@dataclass(frozen=True, slots=True)
class FuzzySignalScore:
    signal_name: str
    left_value: str
    right_value: str
    similarity: float
    weight: float
    contribution: float
    evidence_kind: EvidenceKind


@dataclass(frozen=True, slots=True)
class FuzzyEvaluation:
    left_source_record_id: int
    right_source_record_id: int
    score: float
    decision: MatchDecision
    evidence: tuple[FuzzySignalScore, ...]


@dataclass(frozen=True, slots=True)
class FuzzyMatchRun:
    records_seen: int
    blocked_pairs: int
    pairs_scored: int
    candidates_inserted: int
    candidates_unchanged: int
    evidence_inserted: int


_SIGNALS = (
    FuzzySignal("business_name", 0.40, EvidenceKind.FUZZY, True),
    FuzzySignal("address", 0.30, EvidenceKind.FUZZY, True),
    FuzzySignal("city", 0.10, EvidenceKind.CONTEXT, False),
    FuzzySignal("postal_code", 0.10, EvidenceKind.CONTEXT, False),
    FuzzySignal("domain", 0.05, EvidenceKind.CONTEXT, False),
    FuzzySignal("province", 0.05, EvidenceKind.CONTEXT, False),
    FuzzySignal("parent_organization", 0.10, EvidenceKind.CONTEXT, False),
)

_CANDIDATE_METHOD = "fuzzy_weighted_v1"
_MIN_CORE_SIMILARITY = 0.60
_MIN_CANDIDATE_SCORE = 0.62


def text_similarity(left: str, right: str) -> float:
    """Return a conservative similarity using direct and token-sorted ratios."""
    left_value = " ".join(left.casefold().split())
    right_value = " ".join(right.casefold().split())
    if not left_value or not right_value:
        return 0.0
    if left_value == right_value:
        return 1.0

    direct = SequenceMatcher(None, left_value, right_value).ratio()
    left_tokens = " ".join(sorted(left_value.split()))
    right_tokens = " ".join(sorted(right_value.split()))
    token_sorted = SequenceMatcher(None, left_tokens, right_tokens).ratio()
    return max(direct, token_sorted)


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


def _has_conflicting_location_context(
    left: dict[str, str],
    right: dict[str, str],
) -> bool:
    """Reject candidates when both city and postal code explicitly disagree."""
    fields = ("city", "postal_code")
    comparable = 0
    conflicts = 0

    for field in fields:
        left_value = left.get(field)
        right_value = right.get(field)

        if left_value is None or right_value is None:
            continue

        comparable += 1
        if left_value != right_value:
            conflicts += 1

    return comparable == len(fields) and conflicts == len(fields)


def evaluate_fuzzy_signals(
    left_source_record_id: int,
    left: dict[str, str],
    right_source_record_id: int,
    right: dict[str, str],
) -> FuzzyEvaluation | None:
    if left_source_record_id == right_source_record_id:
        raise FuzzyMatchingError("source record IDs must be distinct")
    if left_source_record_id < 1 or right_source_record_id < 1:
        raise FuzzyMatchingError("source record IDs must be positive integers")

    if left_source_record_id < right_source_record_id:
        left_id, right_id = left_source_record_id, right_source_record_id
        left_values, right_values = left, right
    else:
        left_id, right_id = right_source_record_id, left_source_record_id
        left_values, right_values = right, left

    evidence: list[FuzzySignalScore] = []
    available_weight = 0.0
    weighted_total = 0.0
    core_similarities: list[float] = []

    for signal in _SIGNALS:
        left_value = left_values.get(signal.name)
        right_value = right_values.get(signal.name)
        if left_value is None or right_value is None:
            continue

        similarity = (
            text_similarity(left_value, right_value)
            if signal.fuzzy
            else float(left_value == right_value)
        )
        contribution = signal.weight * similarity
        available_weight += signal.weight
        weighted_total += contribution

        if signal.name in {"business_name", "address"}:
            core_similarities.append(similarity)

        evidence.append(
            FuzzySignalScore(
                signal_name=signal.name,
                left_value=left_value,
                right_value=right_value,
                similarity=similarity,
                weight=signal.weight,
                contribution=contribution,
                evidence_kind=signal.evidence_kind,
            )
        )

    if not evidence or not core_similarities:
        return None
    if max(core_similarities) < _MIN_CORE_SIMILARITY:
        return None

    score = weighted_total / available_weight
    if score < _MIN_CANDIDATE_SCORE:
        return None

    if _has_conflicting_location_context(left_values, right_values):
        return None

    if _has_conflicting_parent_organization(left_values, right_values):
        return None

    return FuzzyEvaluation(
        left_source_record_id=left_id,
        right_source_record_id=right_id,
        score=score,
        decision=MatchDecision.REVIEW,
        evidence=tuple(evidence),
    )


def generate_fuzzy_matches(connection: sqlite3.Connection) -> FuzzyMatchRun:
    signals = _load_latest_normalized_signals(connection)
    blocked_pairs = _blocking_pairs(signals)

    evaluations: list[FuzzyEvaluation] = []
    for left_id, right_id in blocked_pairs:
        evaluation = evaluate_fuzzy_signals(
            left_id,
            signals[left_id],
            right_id,
            signals[right_id],
        )
        if evaluation is not None:
            evaluations.append(evaluation)

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
                )
    except sqlite3.Error as exc:
        raise FuzzyMatchingError(
            f"Fuzzy matching database operation failed: {exc}"
        ) from exc

    return FuzzyMatchRun(
        records_seen=len(signals),
        blocked_pairs=len(blocked_pairs),
        pairs_scored=len(evaluations),
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


def _blocking_pairs(
    signals: dict[int, dict[str, str]],
) -> list[tuple[int, int]]:
    groups: dict[tuple[str, str], list[int]] = defaultdict(list)

    for source_record_id, values in signals.items():
        city = values.get("city")
        province = values.get("province")
        postal_code = values.get("postal_code")
        domain = values.get("domain")

        if city is not None and province is not None:
            groups[("city_province", f"{province}\0{city.casefold()}")].append(
                source_record_id
            )

        if postal_code is not None and len(postal_code) >= 3:
            groups[("postal_fsa", postal_code[:3].upper())].append(source_record_id)

        if domain is not None:
            groups[("domain", domain.casefold())].append(source_record_id)

    pairs: set[tuple[int, int]] = set()
    for grouped_ids in groups.values():
        for left_id, right_id in combinations(sorted(set(grouped_ids)), 2):
            pairs.add((left_id, right_id))

    return sorted(pairs)


def _persist_candidate(
    connection: sqlite3.Connection,
    evaluation: FuzzyEvaluation,
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
        raise FuzzyMatchingError("Match candidate insert returned no row ID")
    return int(cursor.lastrowid), True


def _persist_evidence(
    connection: sqlite3.Connection,
    candidate_id: int,
    evaluation: FuzzyEvaluation,
) -> int:
    inserted = 0

    for item in evaluation.evidence:
        exists = connection.execute(
            """
            SELECT 1
            FROM match_evidence
            WHERE match_candidate_id = ?
              AND signal_name = ?
              AND left_value = ?
              AND right_value = ?
              AND evidence_kind = ?
            LIMIT 1
            """,
            (
                candidate_id,
                item.signal_name,
                item.left_value,
                item.right_value,
                item.evidence_kind.value,
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
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                candidate_id,
                item.signal_name,
                item.left_value,
                item.right_value,
                item.contribution,
                item.evidence_kind.value,
            ),
        )
        inserted += 1

    return inserted
