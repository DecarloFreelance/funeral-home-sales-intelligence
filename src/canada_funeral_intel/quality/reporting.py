from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .scoring import SUBJECT_TYPES, score_all


def quality_summary(
    connection,
    *,
    subject_type: str = "entity",
    reference_time,
    include_historical: bool = False,
    readiness: str | None = None,
    minimum_score: float | None = None,
    maximum_score: float | None = None,
    entity_id: int | None = None,
    conflict_only: bool = False,
    incomplete_only: bool = False,
) -> list[dict[str, Any]]:
    rows = score_all(
        connection,
        subject_type,
        reference_time=reference_time,
        include_historical=include_historical,
    )
    result = []
    for row in rows:
        if readiness is not None and row["readiness"] != readiness:
            continue
        score = row["overall_score"]
        if minimum_score is not None and (score is None or score < minimum_score):
            continue
        if maximum_score is not None and (score is None or score > maximum_score):
            continue
        if entity_id is not None:
            row_entities = row["evidence"].get("entity_ids", [])
            if row["subject_type"] == "entity":
                matches_entity = row["subject_id"] == entity_id
            else:
                matches_entity = (
                    entity_id in row_entities
                    or row["evidence"].get("entity_id") == entity_id
                )
            if not matches_entity:
                continue
        if conflict_only and "conflicting_values" not in row["warnings"]:
            continue
        if incomplete_only and "missing_provenance" not in row["reasons"]:
            continue
        result.append(row)
    return sorted(result, key=lambda row: (row["subject_type"], row["subject_id"]))


def export_quality(
    connection, output: Path, *, reference_time, include_historical: bool = False
) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    rows = [
        row
        for subject_type in SUBJECT_TYPES
        for row in quality_summary(
            connection,
            subject_type=subject_type,
            reference_time=reference_time,
            include_historical=include_historical,
        )
    ]
    score_fields = (
        "subject_type",
        "subject_id",
        "display_name",
        "policy_version",
        "overall_score",
        "readiness",
        "input_fingerprint",
    )
    component_fields = ("subject_type", "subject_id", "component", "score")
    warning_fields = ("subject_type", "subject_id", "kind", "code")
    paths = [
        output / "quality_scores.csv",
        output / "quality_components.csv",
        output / "quality_warnings.csv",
    ]
    with paths[0].open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=score_fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows({field: row[field] for field in score_fields} for row in rows)
    with paths[1].open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=component_fields, lineterminator="\n"
        )
        writer.writeheader()
        for row in rows:
            for component, score in sorted(row["components"].items()):
                writer.writerow(
                    {
                        "subject_type": row["subject_type"],
                        "subject_id": row["subject_id"],
                        "component": component,
                        "score": score,
                    }
                )
    with paths[2].open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=warning_fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            for kind, values in (
                ("reason", row["reasons"]),
                ("warning", row["warnings"]),
            ):
                for value in values:
                    writer.writerow(
                        {
                            "subject_type": row["subject_type"],
                            "subject_id": row["subject_id"],
                            "kind": kind,
                            "code": value,
                        }
                    )
    return paths
