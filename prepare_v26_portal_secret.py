#!/usr/bin/env python3
"""Prepare the authoritative V26 `data/portal_findings.json` for manual
upload as Render's `portal_findings.json` Secret File.

This is deliberately separate from the retired `export_portal_findings.py`,
which belongs to the old V14-V19/955-record/CFI-#### lineage (see
docs/PIPELINE_HISTORY.md) and has no relationship to the hand-maintained
V26 dataset that is actually deployed. This script never reads that old
pipeline's output and never modifies the authoritative source file -- it
only validates it and writes a compact, size-checked copy for someone to
paste into Render's dashboard.

Fails closed (refuses to write anything) unless the source explicitly
identifies itself as the expected V26 snapshot by both its declared
version label and its authoritative record count -- either check alone is
not enough to safely represent the source as V26 (see AGENTS.md and
audit/GAP_REGISTRY.md for why bounded, verified-evidence requirements
exist here).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

SOURCE = Path("data/portal_findings.json")
OUTPUT = Path("instance/portal_findings_v26_secret.json")
EXPECTED_VERSION = "V26"
EXPECTED_RECORD_COUNT = 1302
REQUIRED_KEYS = ("records", "version", "generated", "summary")
MAX_RENDER_SECRET_BYTES = 1_000_000


class SourceValidationError(ValueError):
    """The source artifact does not match the expected V26 shape."""


def load_and_validate(source: Path) -> dict:
    if not source.is_file():
        raise SourceValidationError(f"Source file not found: {source}")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SourceValidationError(f"Source is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SourceValidationError("Source must be a JSON object, not a list or scalar")
    missing = [key for key in REQUIRED_KEYS if key not in payload]
    if missing:
        raise SourceValidationError(f"Source is missing required keys: {missing}")
    if payload.get("version") != EXPECTED_VERSION:
        raise SourceValidationError(
            f"Source version is {payload.get('version')!r}, expected {EXPECTED_VERSION!r}"
        )
    records = payload.get("records")
    if not isinstance(records, list):
        raise SourceValidationError("Source 'records' must be a list")
    if len(records) != EXPECTED_RECORD_COUNT:
        raise SourceValidationError(
            f"Source has {len(records)} records, expected {EXPECTED_RECORD_COUNT}"
        )
    return payload


def write_secret_snapshot(source: Path, output: Path) -> int:
    """Validate `source`, write a compact copy to `output`, and return its
    byte size. Never modifies `source`. Fails closed on any mismatch,
    including a round-trip check of what was actually written."""
    payload = load_and_validate(source)

    compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    size = len(compact.encode("utf-8"))
    if size >= MAX_RENDER_SECRET_BYTES:
        raise SourceValidationError(
            f"Compact snapshot is {size} bytes, at or over Render's "
            f"{MAX_RENDER_SECRET_BYTES}-byte secret-file limit"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(compact, encoding="utf-8")
    try:
        output.chmod(0o600)
    except OSError:
        pass  # best-effort; not every filesystem honors POSIX permission bits

    reparsed = json.loads(output.read_text(encoding="utf-8"))
    if (
        reparsed.get("version") != EXPECTED_VERSION
        or len(reparsed.get("records") or []) != EXPECTED_RECORD_COUNT
    ):
        raise SourceValidationError("Round-trip verification of the written snapshot failed")

    return size


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    try:
        size = write_secret_snapshot(args.source, args.output)
    except SourceValidationError as exc:
        print(f"REFUSED: {exc}")
        return 1

    print(json.dumps({
        "source": str(args.source),
        "output": str(args.output),
        "version": EXPECTED_VERSION,
        "records": EXPECTED_RECORD_COUNT,
        "bytes": size,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
