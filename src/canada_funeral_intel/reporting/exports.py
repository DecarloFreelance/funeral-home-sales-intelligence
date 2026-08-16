from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from . import REPORT_VERSION
from .reports import (
    business_report,
    content_hash,
    coverage_report,
    people_report,
    quality_report,
    stable_json,
)


def export_reports(
    connection, output: Path, *, include_historical: bool = False, reference_time=None
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    reports = {
        "coverage": coverage_report(
            connection,
            include_historical=include_historical,
            reference_time=reference_time,
        ),
        "quality": quality_report(
            connection,
            include_historical=include_historical,
            reference_time=reference_time,
        ),
        "business": business_report(
            connection,
            include_historical=include_historical,
            reference_time=reference_time,
        ),
        "people": people_report(
            connection,
            include_historical=include_historical,
            reference_time=reference_time,
        ),
    }
    paths: list[Path] = []
    for name in sorted(reports):
        path = output / f"report_{name}.json"
        path.write_bytes(stable_json(reports[name]))
        paths.append(path)
    coverage_fields = (
        "definition_id",
        "numerator",
        "denominator",
        "excluded",
        "percentage",
    )
    coverage_path = output / "report_coverage.csv"
    with coverage_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=coverage_fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(reports["coverage"]["metrics"])
    paths.append(coverage_path)
    manifest = {
        "report_version": REPORT_VERSION,
        "reference_time": reports["coverage"]["reference_time"],
        "include_historical": include_historical,
        "files": [],
    }
    for path in sorted(paths, key=lambda value: value.name):
        data = path.read_bytes()
        manifest["files"].append(
            {
                "name": path.name,
                "bytes": len(data),
                "sha256": content_hash(data.decode("utf-8")),
            }
        )
    manifest_path = output / "report_manifest.json"
    manifest_path.write_bytes(stable_json(manifest))
    paths.append(manifest_path)
    return {
        "format": "json-csv",
        "output": str(output),
        "files": [path.name for path in sorted(paths, key=lambda value: value.name)],
        "manifest": manifest,
    }
