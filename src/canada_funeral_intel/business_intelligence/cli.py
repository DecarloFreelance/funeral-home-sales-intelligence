from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from canada_funeral_intel.storage.database import transaction

from .processing import extract_business_facts_from_pages
from .reporting import export_business_facts, summarize_business_facts
from .storage import list_business_facts


class BusinessFactCommandError(RuntimeError):
    """Raised when business-fact processing cannot complete safely."""


def run_business_facts_list(
    connection: sqlite3.Connection, **filters: object
) -> list[dict[str, object]]:
    return list_business_facts(connection, **filters)


def run_business_facts_summary(
    connection: sqlite3.Connection, **filters: object
) -> list[dict[str, object]]:
    return summarize_business_facts(connection, **filters)


def run_business_facts_export(
    connection: sqlite3.Connection, *, output: Path, **filters: object
) -> dict[str, object]:
    return {
        "format": "csv",
        "output": str(output),
        "files": [
            path.name for path in export_business_facts(connection, output, **filters)
        ],
    }


def run_business_facts_extract(
    connection: sqlite3.Connection,
    *,
    website_id: int | None,
    page_id: int | None,
    user_agent: str,
    timeout_seconds: int,
    max_redirects: int,
) -> dict[str, object]:
    try:
        result = extract_business_facts_from_pages(
            connection,
            website_id=website_id,
            page_id=page_id,
            user_agent=user_agent,
            timeout_seconds=timeout_seconds,
            max_redirects=max_redirects,
        )
    except (sqlite3.Error, ValueError) as exc:
        raise BusinessFactCommandError(str(exc)) from exc
    return {
        "pages_selected": result.pages_selected,
        "pages_attempted": result.pages_attempted,
        "pages_succeeded": result.pages_succeeded,
        "pages_failed": result.pages_failed,
        "facts_extracted": result.facts_extracted,
        "facts_inserted": result.facts_inserted,
        "facts_unchanged": result.facts_unchanged,
        "failures": [
            {
                "page_id": failure.page_id,
                "website_id": failure.website_id,
                "error": failure.error,
            }
            for failure in result.failures
        ],
    }


def run_business_facts_agent(
    connection: sqlite3.Connection,
    *,
    model: str,
    output: Path | None,
    provider: str,
    keys_file: Path | None = None,
) -> dict[str, object]:
    from .agent_review import review_business_facts

    try:
        return review_business_facts(
            connection,
            model=model,
            output_path=output,
            provider=provider,
            keys_file=keys_file,
        )
    except (sqlite3.Error, ValueError, RuntimeError) as exc:
        raise BusinessFactCommandError(str(exc)) from exc


def run_business_facts_agent_apply(
    connection: sqlite3.Connection,
    *,
    input_path: Path,
    apply: bool,
) -> dict[str, object]:
    try:
        artifact_bytes = input_path.read_bytes()
        artifact = json.loads(artifact_bytes.decode("utf-8"))
        if not isinstance(artifact, dict):
            raise TypeError("agent artifact must be a JSON object")
        recommendations = artifact.get("recommendations")
        if not isinstance(recommendations, list):
            raise TypeError("agent artifact has no recommendations array")
        run_id = hashlib.sha256(artifact_bytes).hexdigest()
        facts = {int(row["id"]): row for row in list_business_facts(connection)}
        seen: set[int] = set()
        for item in recommendations:
            if not isinstance(item, dict):
                raise TypeError("agent artifact contains a non-object recommendation")
            fact_id = item.get("fact_id")
            if isinstance(fact_id, bool) or not isinstance(fact_id, int):
                raise TypeError("agent artifact contains an invalid fact_id")
            if fact_id not in facts or fact_id in seen:
                raise ValueError(
                    f"agent artifact contains unknown or duplicate fact_id: {fact_id}"
                )
            if item.get("disposition") not in {"keep", "flag", "reject"}:
                raise ValueError(f"invalid disposition for fact_id {fact_id}")
            if (
                not isinstance(item.get("rationale"), str)
                or not item["rationale"].strip()
            ):
                raise ValueError(f"missing rationale for fact_id {fact_id}")
            if (
                not isinstance(item.get("evidence_reference"), str)
                or not item["evidence_reference"].strip()
            ):
                raise ValueError(f"missing evidence reference for fact_id {fact_id}")
            seen.add(fact_id)
        current_ids = set(facts)
        if seen != current_ids:
            missing = sorted(current_ids - seen)
            raise ValueError(
                f"agent artifact does not cover all current facts; missing: {missing}"
            )
        result = {
            "applied": False,
            "database_changed": False,
            "artifact_sha256": run_id,
            "fact_count": len(recommendations),
            "input": str(input_path),
            "run_id": run_id,
            "counts": {
                disposition: sum(
                    1 for item in recommendations if item["disposition"] == disposition
                )
                for disposition in ("keep", "flag", "reject")
            },
        }
        if apply:
            with transaction(connection):
                for item in recommendations:
                    connection.execute(
                        "INSERT INTO business_fact_agent_reviews (run_id, fact_id, disposition, confidence, rationale, evidence_reference, provider, model, prompt_version, artifact_sha256) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            run_id,
                            item["fact_id"],
                            item["disposition"],
                            item["confidence"],
                            item["rationale"],
                            item["evidence_reference"],
                            artifact.get("provider", "unknown"),
                            artifact.get("model", "unknown"),
                            artifact.get("prompt_version", "unknown"),
                            run_id,
                        ),
                    )
            result["applied"] = True
            result["database_changed"] = True
        return result
    except (OSError, json.JSONDecodeError, sqlite3.Error, TypeError, ValueError) as exc:
        raise BusinessFactCommandError(str(exc)) from exc
