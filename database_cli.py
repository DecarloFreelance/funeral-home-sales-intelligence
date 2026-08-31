#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from persistence.importer import (
    DEFAULT_CRM, DEFAULT_DIRECTORY, build_bundle, database_counts, import_bundle, integrity_report,
)
from persistence.coverage import (
    DEFAULT_MAPPINGS, DEFAULT_PAGES, DEFAULT_REPORT, build_coverage_bundle,
    coverage_counts, import_coverage,
)
from persistence.migrations import migrate, status
from persistence.postgres import PsqlRunner


def emit(value) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description="Operate the credential-safe FHSI PostgreSQL persistence layer.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("connect", help="Test TLS database connectivity without exposing credentials.")
    sub.add_parser("migrate", help="Apply pending non-destructive migrations transactionally.")
    sub.add_parser("status", help="Show migration status.")
    importer = sub.add_parser("import", help="Validate or import canonical JSON and a read-only CRM snapshot.")
    importer.add_argument("--directory", type=Path, default=DEFAULT_DIRECTORY)
    importer.add_argument("--crm", type=Path, default=DEFAULT_CRM)
    mode = importer.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    validator = sub.add_parser("validate", help="Compare source/database counts and run integrity checks.")
    validator.add_argument("--directory", type=Path, default=DEFAULT_DIRECTORY)
    validator.add_argument("--crm", type=Path, default=DEFAULT_CRM)
    coverage = sub.add_parser("coverage", help="Validate or import reviewed website/crawl coverage.")
    coverage.add_argument("--mappings", type=Path, default=DEFAULT_MAPPINGS)
    coverage.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    coverage.add_argument("--pages", type=Path, default=DEFAULT_PAGES)
    coverage_mode = coverage.add_mutually_exclusive_group(required=True)
    coverage_mode.add_argument("--dry-run", action="store_true")
    coverage_mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.command == "import" and args.dry_run:
        bundle = build_bundle(args.directory, args.crm)
        emit({"dry_run": True, "source_counts": bundle.counts()})
        return 0
    if args.command == "coverage" and args.dry_run:
        bundle = build_coverage_bundle(args.mappings, args.report, args.pages)
        emit({"dry_run": True, "source_counts": bundle.counts()})
        return 0

    runner = PsqlRunner()
    if args.command == "connect":
        output = runner.run(
            "SELECT current_database() || '|' || "
            "COALESCE((SELECT CASE WHEN ssl THEN 'true' ELSE 'false' END "
            "FROM pg_stat_ssl WHERE pid = pg_backend_pid()), 'unavailable') || '|' || "
            "COALESCE((SELECT version FROM pg_stat_ssl WHERE pid = pg_backend_pid()), 'pooler-managed');",
            tuples_only=True,
        )
        database, observed_tls, version = output.split("|", 2)
        emit({
            "connected": True, "database": database,
            "tls_enforced": runner.config.sslmode in {"require", "verify-ca", "verify-full"},
            "sslmode": runner.config.sslmode,
            "server_tls_observed": None if observed_tls == "unavailable" else observed_tls == "true",
            "server_tls_version": version,
        })
    elif args.command == "migrate":
        emit({"applied": migrate(runner), "status": status(runner)})
    elif args.command == "status":
        emit({"migrations": status(runner)})
    elif args.command == "import":
        bundle = build_bundle(args.directory, args.crm)
        result = {"dry_run": False, "source_counts": bundle.counts()}
        result["imported_counts"] = import_bundle(runner, bundle)
        result["database_counts"] = database_counts(runner)
        result["skipped_records"] = 0
        result["conflicting_records"] = 0
        result["conflict_policy"] = "abort_transaction_on_cross-source_organization_id"
        emit(result)
    elif args.command == "validate":
        bundle = build_bundle(args.directory, args.crm)
        source = bundle.counts()
        database = database_counts(runner)
        integrity = integrity_report(runner)
        mismatches = {key: {"source": value, "database": database.get(key)} for key, value in source.items() if database.get(key) != value}
        failures = {key: value for key, value in integrity.items() if value}
        emit({"source_counts": source, "database_counts": database, "count_mismatches": mismatches, "integrity": integrity})
        return 1 if mismatches or failures else 0
    elif args.command == "coverage":
        bundle = build_coverage_bundle(args.mappings, args.report, args.pages)
        imported = import_coverage(runner, bundle)
        database = coverage_counts(runner)
        expected = bundle.counts()
        mismatches = {key: {"source": value, "database": database.get(key)} for key, value in expected.items() if database.get(key) != value}
        emit({"dry_run": False, "source_counts": expected, "imported_counts": imported,
              "database_counts": database, "count_mismatches": mismatches})
        return 1 if mismatches else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
