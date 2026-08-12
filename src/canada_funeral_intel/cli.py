from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .collectors.afsrb_cli import (
    AFSRB_SOURCE_NAME,
    AfsrbProbeCommandError,
    print_afsrb_probe_result,
    run_afsrb_probe,
)
from .collectors.import_cli import (
    ImportCommandError,
    print_import_result,
    run_import_command,
)
from .collectors.importers import ImportFormat
from .collectors.source_registry import (
    SourceDefinition,
    SourceRegistryError,
    load_source_registry,
)
from .collectors.source_registry_storage import seed_source_registry
from .config import ConfigurationError, load_settings
from .deduplication.merge_cli import (
    MergeCommandError,
    print_merge_payload,
    run_merge_apply,
    run_merge_rollback,
)
from .deduplication.review import ReviewStatus
from .deduplication.review_cli import (
    ReviewCommandError,
    print_review_payload,
    run_review_decide,
    run_review_list,
    run_review_populate,
)
from .logging_config import configure_logging
from .normalization.cli import (
    NormalizeCommandError,
    print_normalize_result,
    run_normalize_command,
)
from .storage import DatabaseError, database_session
from .storage.migrations import (
    MigrationError,
    apply_pending_migrations,
    migration_status,
)
from .verification.models import WebsiteReviewStatus
from .verification.website_cli import (
    WebsiteCommandError,
    print_website_payload,
    run_website_checks,
    run_website_crawl,
    run_website_discover,
    run_website_list,
    run_website_pages,
    run_website_review_decide,
    run_website_review_list,
    run_website_verify,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION_DIR = _PROJECT_ROOT / "database" / "migrations"
_SOURCE_REGISTRY_PATH = _PROJECT_ROOT / "config" / "sources.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="canada_funeral_intel",
        description="Canada Funeral Intelligence command-line interface.",
    )
    subparsers = parser.add_subparsers(dest="command")

    config_parser = subparsers.add_parser(
        "config",
        help="Inspect application configuration.",
    )
    config_subparsers = config_parser.add_subparsers(dest="config_command")
    config_subparsers.add_parser(
        "show",
        help="Show resolved, non-secret configuration.",
    )

    db_parser = subparsers.add_parser(
        "db",
        help="Manage the application database.",
    )
    db_subparsers = db_parser.add_subparsers(dest="db_command")
    db_subparsers.add_parser(
        "init",
        help="Initialize the database and apply pending migrations.",
    )
    db_subparsers.add_parser(
        "migrate",
        help="Apply pending database migrations.",
    )
    db_subparsers.add_parser(
        "status",
        help="Show database migration status.",
    )

    sources_parser = subparsers.add_parser(
        "sources",
        help="Inspect and validate the source registry.",
    )
    sources_subparsers = sources_parser.add_subparsers(
        dest="sources_command",
    )
    sources_subparsers.add_parser(
        "list",
        help="List configured source definitions.",
    )
    sources_subparsers.add_parser(
        "validate",
        help="Validate the configured source registry.",
    )
    sources_subparsers.add_parser(
        "seed",
        help="Synchronize configured source metadata into the database.",
    )
    sources_show_parser = sources_subparsers.add_parser(
        "show",
        help="Show one configured source definition.",
    )
    sources_show_parser.add_argument(
        "name",
        help="Source name to display.",
    )

    sources_probe_parser = sources_subparsers.add_parser(
        "probe",
        help="Probe supported live source metadata without database writes.",
    )
    sources_probe_parser.add_argument(
        "name",
        nargs="?",
        default=AFSRB_SOURCE_NAME,
        help="Registered source name; defaults to the Alberta regulator.",
    )

    sources_collect_parser = sources_subparsers.add_parser(
        "collect",
        help="Collect a supported live registered source into raw source records.",
    )
    sources_collect_parser.add_argument(
        "name",
        nargs="?",
        default="Funeral Board of Manitoba",
        help="Registered live source name; defaults to Funeral Board of Manitoba.",
    )
    sources_collect_parser.add_argument(
        "--timeout",
        type=float,
        help="Optional HTTP timeout in seconds.",
    )

    import_parser = subparsers.add_parser(
        "import",
        help="Import a registered CSV or JSON source dataset.",
    )
    import_parser.add_argument(
        "path",
        type=Path,
        help="Path to the source file.",
    )
    import_parser.add_argument(
        "--source",
        required=True,
        help="Registered source name.",
    )
    import_parser.add_argument(
        "--format",
        dest="import_format",
        required=True,
        choices=tuple(item.value for item in ImportFormat),
        help="Input file format.",
    )
    import_parser.add_argument(
        "--external-id-field",
        help="Optional field containing the source record identifier.",
    )

    normalize_parser = subparsers.add_parser(
        "normalize",
        help="Normalize imported source records.",
    )
    normalize_parser.add_argument(
        "--source",
        help="Optional registered source name to normalize.",
    )

    merge_parser = subparsers.add_parser(
        "merge",
        help="Apply and roll back entity merges.",
    )
    merge_subparsers = merge_parser.add_subparsers(dest="merge_command")

    merge_apply_parser = merge_subparsers.add_parser(
        "apply",
        help="Merge one entity into a survivor entity.",
    )
    merge_apply_parser.add_argument(
        "survivor_entity_id",
        type=int,
        help="Entity ID that survives the merge.",
    )
    merge_apply_parser.add_argument(
        "merged_entity_id",
        type=int,
        help="Entity ID that is merged into the survivor.",
    )
    merge_apply_parser.add_argument(
        "--source",
        required=True,
        dest="decision_source",
        help="Decision source such as manual_review or automatic.",
    )
    merge_apply_parser.add_argument(
        "--reason",
        required=True,
        help="Reason for the merge.",
    )

    merge_rollback_parser = merge_subparsers.add_parser(
        "rollback",
        help="Roll back a recorded entity merge.",
    )
    merge_rollback_parser.add_argument(
        "merge_history_id",
        type=int,
        help="Merge history entry ID to roll back.",
    )

    review_parser = subparsers.add_parser(
        "review",
        help="Manage manual entity-resolution review candidates.",
    )
    review_subparsers = review_parser.add_subparsers(dest="review_command")
    review_subparsers.add_parser(
        "populate",
        help="Add review candidates to the manual review queue.",
    )
    review_list_parser = review_subparsers.add_parser(
        "list",
        help="List manual review queue entries.",
    )
    review_list_parser.add_argument(
        "--status",
        choices=("pending", "approved", "rejected", "deferred", "all"),
        default="pending",
        help="Review status to list (default: pending).",
    )
    review_decide_parser = review_subparsers.add_parser(
        "decide",
        help="Apply a manual review decision.",
    )
    review_decide_parser.add_argument(
        "queue_id",
        type=int,
        help="Review queue entry ID.",
    )
    review_decide_parser.add_argument(
        "--decision",
        required=True,
        choices=("approved", "rejected", "deferred"),
        help="Manual review decision.",
    )
    review_decide_parser.add_argument(
        "--note",
        help="Optional reviewer note.",
    )

    website_parser = subparsers.add_parser(
        "website",
        help="Discover and review website candidates.",
    )
    website_subparsers = website_parser.add_subparsers(
        dest="website_command",
    )
    website_subparsers.add_parser(
        "discover",
        help="Discover website candidates from normalized source data.",
    )
    website_list_parser = website_subparsers.add_parser(
        "list",
        help="List discovered website candidates.",
    )
    website_list_parser.add_argument(
        "--entity-id",
        type=int,
        help="Optional entity ID to list.",
    )

    website_verify_parser = website_subparsers.add_parser(
        "verify",
        help="Verify a website candidate and store the check result.",
    )
    website_verify_parser.add_argument(
        "website_id",
        type=int,
        help="Website candidate ID to verify.",
    )
    website_verify_parser.add_argument(
        "--user-agent",
        default="canada-funeral-intel/0.1",
        help="HTTP User-Agent for the verification request.",
    )
    website_verify_parser.add_argument(
        "--timeout",
        type=int,
        default=10,
        help="Per-network-operation timeout in seconds (default: 10).",
    )
    website_verify_parser.add_argument(
        "--max-redirects",
        type=int,
        default=5,
        help="Maximum redirects to follow (default: 5).",
    )

    website_checks_parser = website_subparsers.add_parser(
        "checks",
        help="List stored website verification history.",
    )
    website_checks_parser.add_argument(
        "--website-id",
        type=int,
        help="Optional website candidate ID to filter.",
    )

    website_crawl_parser = website_subparsers.add_parser(
        "crawl",
        help="Discover relevant pages with a bounded same-site crawl.",
    )
    website_crawl_parser.add_argument(
        "website_id",
        type=int,
        help="Website candidate ID to crawl.",
    )
    website_crawl_parser.add_argument(
        "--user-agent",
        default="CanadaFuneralIntel/0.1",
        help="HTTP User-Agent for page discovery.",
    )
    website_crawl_parser.add_argument(
        "--timeout",
        type=int,
        default=10,
        help="Per-network-operation timeout in seconds (default: 10).",
    )
    website_crawl_parser.add_argument(
        "--max-redirects",
        type=int,
        default=5,
        help="Maximum redirects per request (default: 5).",
    )
    website_crawl_parser.add_argument(
        "--max-pages",
        type=int,
        default=25,
        help="Maximum pages to request (default: 25, maximum: 100).",
    )
    website_crawl_parser.add_argument(
        "--max-depth",
        type=int,
        default=2,
        help="Maximum same-site link depth (default: 2, maximum: 5).",
    )

    website_pages_parser = website_subparsers.add_parser(
        "pages",
        help="List pages discovered for website candidates.",
    )
    website_pages_parser.add_argument(
        "--website-id",
        type=int,
        help="Optional website candidate ID to filter.",
    )

    website_review_parser = website_subparsers.add_parser(
        "review",
        help="Manage the website review queue.",
    )
    website_review_subparsers = website_review_parser.add_subparsers(
        dest="website_review_command",
    )

    website_review_list_parser = website_review_subparsers.add_parser(
        "list",
        help="List website review queue entries.",
    )
    website_review_list_parser.add_argument(
        "--status",
        choices=(
            "pending",
            "approved",
            "rejected",
            "deferred",
            "all",
        ),
        default="pending",
        help="Review status to list (default: pending).",
    )

    website_review_decide_parser = website_review_subparsers.add_parser(
        "decide",
        help="Apply a website review decision.",
    )
    website_review_decide_parser.add_argument(
        "queue_id",
        type=int,
        help="Website review queue entry ID.",
    )
    website_review_decide_parser.add_argument(
        "--decision",
        required=True,
        choices=("approved", "rejected", "deferred"),
        help="Website review decision.",
    )
    website_review_decide_parser.add_argument(
        "--note",
        help="Optional reviewer note.",
    )

    return parser


def _migration_summary(
    database_path: Path,
    *,
    applied_count: int,
    current_version: int,
) -> dict[str, object]:
    return {
        "database_path": str(database_path),
        "applied_migrations": applied_count,
        "current_version": current_version,
    }


def _run_db_apply(database_path: Path) -> int:
    with database_session(database_path) as connection:
        result = apply_pending_migrations(connection, _MIGRATION_DIR)

    print(
        json.dumps(
            _migration_summary(
                database_path,
                applied_count=len(result.applied),
                current_version=result.status.current_version,
            ),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _run_db_status(database_path: Path) -> int:
    existed_before = database_path.exists()

    with database_session(database_path) as connection:
        status = migration_status(connection, _MIGRATION_DIR)

    payload = {
        "database_path": str(database_path),
        "database_exists": existed_before,
        "discovered_migrations": len(status.discovered),
        "applied_migrations": len(status.applied),
        "pending_migrations": len(status.pending),
        "current_version": status.current_version,
        "consistent": status.consistent,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _source_payload(
    source: SourceDefinition,
) -> dict[str, object]:
    return {
        "name": source.name,
        "source_type": source.source_type.value,
        "source_format": source.source_format.value,
        "trust_level": source.trust_level.value,
        "coverage": list(source.coverage),
        "refresh_interval_days": source.refresh_interval_days,
        "enabled": source.enabled,
        "source_url": source.source_url,
        "publisher": source.publisher,
        "jurisdiction": source.jurisdiction,
        "license_name": source.license_name,
        "license_url": source.license_url,
        "licensing_notes": source.licensing_notes,
        "notes": source.notes,
    }


def _load_registry() -> tuple[SourceDefinition, ...]:
    return load_source_registry(_SOURCE_REGISTRY_PATH)


def _run_sources_validate() -> int:
    registry = _load_registry()
    payload = {
        "valid": True,
        "count": len(registry),
        "registry_path": str(_SOURCE_REGISTRY_PATH),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _run_sources_seed(database_path: Path) -> int:
    registry = _load_registry()

    with database_session(database_path) as connection:
        apply_pending_migrations(connection, _MIGRATION_DIR)
        result = seed_source_registry(connection, registry)
        connection.commit()

    payload = {
        "database_path": str(database_path),
        "registry_path": str(_SOURCE_REGISTRY_PATH),
        "definitions": len(registry),
        "inserted": result.inserted,
        "updated": result.updated,
        "unchanged": result.unchanged,
        "total": result.total,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _run_sources_list() -> int:
    registry = _load_registry()
    payload = [_source_payload(source) for source in registry]
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _run_sources_show(name: str) -> int:
    registry = _load_registry()
    requested = name.casefold()

    for source in registry:
        if source.name.casefold() == requested:
            print(
                json.dumps(
                    _source_payload(source),
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

    raise SourceRegistryError(f"Source not found: {name}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        settings = load_settings()
    except ConfigurationError as exc:
        parser.exit(2, f"configuration error: {exc}\n")

    configure_logging(settings.log_level)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "config":
        if args.config_command == "show":
            print(json.dumps(settings.as_display_dict(), indent=2, sort_keys=True))
            return 0
        parser.parse_args(["config", "--help"])
        return 2

    if args.command == "sources" and args.sources_command == "collect":
        from canada_funeral_intel.collectors.manitoba_cli import (
            ManitobaCollectCommandError,
            run_manitoba_collect_command,
        )

        try:
            timeout_seconds = (
                args.timeout
                if args.timeout is not None
                else settings.http_timeout_seconds
            )
            with database_session(settings.database_path) as connection:
                payload = run_manitoba_collect_command(
                    connection,
                    migration_dir=_MIGRATION_DIR,
                    registry_path=_SOURCE_REGISTRY_PATH,
                    source_name=args.name,
                    user_agent=settings.http_user_agent,
                    timeout_seconds=timeout_seconds,
                )
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0
        except (DatabaseError, ManitobaCollectCommandError) as exc:
            print(f"collection error: {exc}", file=sys.stderr)
            return 5

    if args.command == "import":
        try:
            with database_session(settings.database_path) as connection:
                payload = run_import_command(
                    connection,
                    migration_dir=_MIGRATION_DIR,
                    registry_path=_SOURCE_REGISTRY_PATH,
                    source_name=args.source,
                    input_path=args.path,
                    input_format=ImportFormat(args.import_format),
                    external_id_field=args.external_id_field,
                )
            print_import_result(payload)
            return 0
        except (DatabaseError, ImportCommandError) as exc:
            print(f"import error: {exc}", file=sys.stderr)
            return 5

    if args.command == "normalize":
        try:
            with database_session(settings.database_path) as connection:
                payload = run_normalize_command(
                    connection,
                    migration_dir=_MIGRATION_DIR,
                    registry_path=_SOURCE_REGISTRY_PATH,
                    source_name=args.source,
                )
            print_normalize_result(payload)
            return 0
        except (DatabaseError, NormalizeCommandError) as exc:
            print(f"normalize error: {exc}", file=sys.stderr)
            return 6

    if args.command == "merge":
        if args.merge_command is None:
            parser.parse_args(["merge", "--help"])
            return 2

        try:
            with database_session(settings.database_path) as connection:
                if args.merge_command == "apply":
                    payload = run_merge_apply(
                        connection,
                        survivor_entity_id=args.survivor_entity_id,
                        merged_entity_id=args.merged_entity_id,
                        decision_source=args.decision_source,
                        reason=args.reason,
                    )
                elif args.merge_command == "rollback":
                    payload = run_merge_rollback(
                        connection,
                        merge_history_id=args.merge_history_id,
                    )
                else:
                    parser.parse_args(["merge", "--help"])
                    return 2

            print_merge_payload(payload)
            return 0
        except (DatabaseError, MergeCommandError) as exc:
            print(f"merge error: {exc}", file=sys.stderr)
            return 8

    if args.command == "review":
        if args.review_command is None:
            parser.parse_args(["review", "--help"])
            return 2

        try:
            with database_session(settings.database_path) as connection:
                if args.review_command == "populate":
                    payload = run_review_populate(connection)
                elif args.review_command == "list":
                    status = None if args.status == "all" else ReviewStatus(args.status)
                    payload = run_review_list(connection, status=status)
                elif args.review_command == "decide":
                    payload = run_review_decide(
                        connection,
                        queue_id=args.queue_id,
                        status=ReviewStatus(args.decision),
                        reviewer_note=args.note,
                    )
                else:
                    parser.parse_args(["review", "--help"])
                    return 2
            print_review_payload(payload)
            return 0
        except (DatabaseError, ReviewCommandError) as exc:
            print(f"review error: {exc}", file=sys.stderr)
            return 7

    if args.command == "website":
        if args.website_command is None:
            parser.parse_args(["website", "--help"])
            return 2

        try:
            with database_session(settings.database_path) as connection:
                if args.website_command == "discover":
                    payload = run_website_discover(connection)

                elif args.website_command == "list":
                    payload = run_website_list(
                        connection,
                        entity_id=args.entity_id,
                    )

                elif args.website_command == "verify":
                    payload = run_website_verify(
                        connection,
                        website_id=args.website_id,
                        user_agent=args.user_agent,
                        timeout_seconds=args.timeout,
                        max_redirects=args.max_redirects,
                    )

                elif args.website_command == "checks":
                    payload = run_website_checks(
                        connection,
                        website_id=args.website_id,
                    )

                elif args.website_command == "crawl":
                    payload = run_website_crawl(
                        connection,
                        website_id=args.website_id,
                        user_agent=args.user_agent,
                        timeout_seconds=args.timeout,
                        max_redirects=args.max_redirects,
                        max_pages=args.max_pages,
                        max_depth=args.max_depth,
                    )

                elif args.website_command == "pages":
                    payload = run_website_pages(
                        connection,
                        website_id=args.website_id,
                    )

                elif args.website_command == "review":
                    if args.website_review_command is None:
                        parser.parse_args(["website", "review", "--help"])
                        return 2

                    if args.website_review_command == "list":
                        review_status = (
                            None
                            if args.status == "all"
                            else WebsiteReviewStatus(args.status)
                        )
                        payload = run_website_review_list(
                            connection,
                            status=review_status,
                        )

                    elif args.website_review_command == "decide":
                        payload = run_website_review_decide(
                            connection,
                            queue_id=args.queue_id,
                            status=WebsiteReviewStatus(args.decision),
                            reviewer_note=args.note,
                        )

                    else:
                        parser.parse_args(["website", "review", "--help"])
                        return 2

                else:
                    parser.parse_args(["website", "--help"])
                    return 2

            print_website_payload(payload)
            return 0

        except (
            DatabaseError,
            WebsiteCommandError,
        ) as exc:
            print(
                f"website error: {exc}",
                file=sys.stderr,
            )
            return 9

    if args.command == "sources":
        if args.sources_command is None:
            parser.parse_args(["sources", "--help"])
            return 2

        try:
            if args.sources_command == "validate":
                return _run_sources_validate()
            if args.sources_command == "seed":
                return _run_sources_seed(settings.database_path)
            if args.sources_command == "list":
                return _run_sources_list()
            if args.sources_command == "show":
                return _run_sources_show(args.name)
            if args.sources_command == "probe":
                payload = run_afsrb_probe(
                    _SOURCE_REGISTRY_PATH,
                    source_name=args.name,
                )
                print_afsrb_probe_result(payload)
                return 0
        except (
            SourceRegistryError,
            AfsrbProbeCommandError,
            DatabaseError,
            MigrationError,
        ) as exc:
            print(f"source registry error: {exc}", file=sys.stderr)
            return 4

    if args.command == "db":
        if args.db_command is None:
            parser.parse_args(["db", "--help"])
            return 2

        try:
            if args.db_command in {"init", "migrate"}:
                return _run_db_apply(settings.database_path)
            if args.db_command == "status":
                return _run_db_status(settings.database_path)
        except (DatabaseError, MigrationError) as exc:
            print(f"database error: {exc}", file=sys.stderr)
            return 3

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
