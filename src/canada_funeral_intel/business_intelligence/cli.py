from __future__ import annotations

import sqlite3
from pathlib import Path

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
