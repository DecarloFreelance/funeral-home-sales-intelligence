from __future__ import annotations

import csv
from pathlib import Path

from .storage import list_business_facts


def _latest_fact_dispositions(connection) -> dict[int, str]:
    rows = connection.execute(
        """
        SELECT r.fact_id, r.disposition
        FROM business_fact_agent_reviews AS r
        JOIN (
            SELECT fact_id, MAX(id) AS latest_id
            FROM business_fact_agent_reviews
            GROUP BY fact_id
        ) AS latest ON latest.latest_id = r.id
        """
    ).fetchall()
    return {int(row["fact_id"]): str(row["disposition"]) for row in rows}


def summarize_business_facts(connection, **filters: object) -> list[dict[str, object]]:
    rows = list_business_facts(connection, **filters)
    dispositions = _latest_fact_dispositions(connection)
    rows = [row for row in rows if dispositions.get(int(row["id"])) != "reject"]
    groups: dict[tuple[object, ...], list[dict[str, object]]] = {}
    for row in rows:
        key = (
            row["entity_id"],
            row["website_id"],
            row["website_page_id"],
            row["fact_key"],
            row["scope"],
            row["scope_entity_id"],
        )
        groups.setdefault(key, []).append(row)
    result = []
    for key, values in sorted(
        groups.items(), key=lambda item: tuple(str(value) for value in item[0])
    ):
        normalized = sorted({str(value["normalized_value"]) for value in values})
        result.append(
            {
                "entity_id": key[0],
                "website_id": key[1],
                "website_page_id": key[2],
                "fact_key": key[3],
                "scope": key[4],
                "scope_entity_id": key[5],
                "observation_count": len(values),
                "values": normalized,
                "state": "ambiguous_scope"
                if key[4] == "ambiguous"
                else (
                    "conflict"
                    if len(normalized) > 1
                    else ("repeated" if len(values) > 1 else "observed")
                ),
            }
        )
    return result


def export_business_facts(connection, output: Path, **filters: object) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    rows = list_business_facts(connection, **filters)
    summaries = summarize_business_facts(connection, **filters)
    columns = (
        "id",
        "website_page_id",
        "website_id",
        "entity_id",
        "source_url",
        "page_kind",
        "fact_key",
        "value_kind",
        "raw_value",
        "normalized_value",
        "scope",
        "scope_entity_id",
        "confidence",
        "extraction_method",
        "extractor_version",
        "evidence_snippet",
        "content_hash",
        "observed_at",
        "created_at",
    )
    summary_columns = (
        "entity_id",
        "website_id",
        "website_page_id",
        "fact_key",
        "scope",
        "scope_entity_id",
        "observation_count",
        "values",
        "state",
    )
    paths = [output / "business_facts.csv", output / "business_fact_summary.csv"]
    for path, data, fields in (
        (paths[0], rows, columns),
        (paths[1], summaries, summary_columns),
    ):
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            for row in data:
                writer.writerow(
                    {
                        field: (
                            "|".join(str(value) for value in row[field])
                            if isinstance(row.get(field), list)
                            else row.get(field)
                        )
                        for field in fields
                    }
                )
    return paths
