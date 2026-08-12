from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from canada_funeral_intel.storage.database import DatabaseError

from .reporting import export_quality, quality_summary
from .scoring import score_one


@contextmanager
def quality_database_session(path: Path):
    database_path = Path(path).expanduser().resolve()
    try:
        connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise DatabaseError(f"Unable to open read-only SQLite database at {database_path}: {exc}") from exc
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
    finally:
        connection.close()


def parse_reference_time(value: str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("reference time must include a timezone")
    return parsed


def run_quality_score(connection: sqlite3.Connection, *, subject_type: str, subject_id: int, reference_time: datetime, include_historical: bool = False):
    return score_one(connection, subject_type, subject_id, reference_time=reference_time, include_historical=include_historical)


def run_quality_summary(connection: sqlite3.Connection, **kwargs):
    return quality_summary(connection, **kwargs)


def run_quality_export(connection: sqlite3.Connection, *, output: Path, reference_time: datetime, include_historical: bool = False):
    return {"format": "csv", "output": str(output), "files": [path.name for path in export_quality(connection, output, reference_time=reference_time, include_historical=include_historical)]}
