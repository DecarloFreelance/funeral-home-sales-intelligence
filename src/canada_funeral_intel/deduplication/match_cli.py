from __future__ import annotations

import json
import sqlite3
from enum import StrEnum

from canada_funeral_intel.deduplication.deterministic import (
    DeterministicMatchingError,
    generate_deterministic_matches,
)
from canada_funeral_intel.deduplication.fuzzy import (
    FuzzyMatchingError,
    generate_fuzzy_matches,
)


class MatchCommandError(RuntimeError):
    """Raised when a matching CLI command cannot complete safely."""


class MatchMode(StrEnum):
    DETERMINISTIC = "deterministic"
    FUZZY = "fuzzy"
    ALL = "all"


def run_match_command(
    connection: sqlite3.Connection,
    *,
    mode: MatchMode,
) -> dict[str, object]:
    try:
        payload: dict[str, object] = {
            "mode": mode.value,
        }

        if mode in {
            MatchMode.DETERMINISTIC,
            MatchMode.ALL,
        }:
            result = generate_deterministic_matches(connection)
            payload["deterministic"] = {
                "records_seen": result.records_seen,
                "pairs_found": result.pairs_found,
                "candidates_inserted": result.candidates_inserted,
                "candidates_unchanged": result.candidates_unchanged,
                "evidence_inserted": result.evidence_inserted,
            }

        if mode in {
            MatchMode.FUZZY,
            MatchMode.ALL,
        }:
            result = generate_fuzzy_matches(connection)
            payload["fuzzy"] = {
                "records_seen": result.records_seen,
                "blocked_pairs": result.blocked_pairs,
                "pairs_scored": result.pairs_scored,
                "candidates_inserted": result.candidates_inserted,
                "candidates_unchanged": result.candidates_unchanged,
                "evidence_inserted": result.evidence_inserted,
            }

        return payload
    except (
        DeterministicMatchingError,
        FuzzyMatchingError,
        sqlite3.Error,
        ValueError,
    ) as exc:
        raise MatchCommandError(str(exc)) from exc


def print_match_payload(payload: object) -> None:
    print(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
        )
    )
