from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .exports import export_reports
from .reports import (
    business_report,
    coverage_report,
    people_report,
    quality_report,
    summary_report,
)


def parse_reference_time(value: str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("reference time must include a timezone")
    return result


def run_report(connection: sqlite3.Connection, report_type: str, *, include_historical: bool, reference_time: datetime):
    if report_type == "coverage": return coverage_report(connection, include_historical=include_historical, reference_time=reference_time)
    if report_type == "quality": return quality_report(connection, include_historical=include_historical, reference_time=reference_time)
    if report_type == "business": return business_report(connection, include_historical=include_historical, reference_time=reference_time)
    if report_type == "people": return people_report(connection, include_historical=include_historical, reference_time=reference_time)
    if report_type == "summary": return summary_report(connection, include_historical=include_historical, reference_time=reference_time)
    raise ValueError(f"Unknown report type: {report_type}")


def run_report_export(connection: sqlite3.Connection, *, output: Path, include_historical: bool, reference_time: datetime):
    return export_reports(connection, output, include_historical=include_historical, reference_time=reference_time)
