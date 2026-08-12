from __future__ import annotations

import sqlite3
from pathlib import Path

from .reporting import export_business_facts, summarize_business_facts
from .storage import list_business_facts


def run_business_facts_list(connection: sqlite3.Connection, **filters: object) -> list[dict[str, object]]:
    return list_business_facts(connection, **filters)


def run_business_facts_summary(connection: sqlite3.Connection, **filters: object) -> list[dict[str, object]]:
    return summarize_business_facts(connection, **filters)


def run_business_facts_export(connection: sqlite3.Connection, *, output: Path, **filters: object) -> dict[str, object]:
    return {"format": "csv", "output": str(output), "files": [path.name for path in export_business_facts(connection, output, **filters)]}
