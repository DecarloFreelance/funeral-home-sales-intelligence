from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .business_intelligence.cli import (
    BusinessFactCommandError,
    run_business_facts_export,
    run_business_facts_extract,
    run_business_facts_list,
    run_business_facts_summary,
)
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
from .deduplication.entity_cli import (
    EntityCommandError,
    print_entity_payload,
    run_entity_materialize,
)
from .deduplication.match_cli import (
    MatchCommandError,
    MatchMode,
    print_match_payload,
    run_match_command,
)
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
from .people.cli import (
    PeopleCommandError,
    print_people_payload,
    run_anomaly_review_decide,
    run_anomaly_review_history,
    run_anomaly_review_list,
    run_anomaly_review_show,
    run_anomaly_sync,
    run_people_audit,
    run_people_audit_list,
    run_people_export,
    run_people_list,
    run_people_merge,
    run_people_resolve,
    run_people_review_backlog,
    run_people_review_decide,
    run_people_review_list,
    run_people_review_populate,
    run_people_rollback,
    run_people_show,
    run_people_triage,
    run_remediation_create,
    run_remediation_history,
    run_remediation_list,
    run_remediation_show,
    run_remediation_sync,
    run_remediation_update,
    run_work_queue_export,
    run_work_queue_list,
    run_work_queue_owners,
    run_work_queue_show,
)
from .people.dispositions import DispositionStatus
from .people.models import PersonReviewStatus
from .people.remediation import TASK_TYPES, RemediationStatus
from .people.triage import TriageFilters, TriageSeverity
from .people.work_queue import WorkQueueFilters
from .pipeline.cli import (
    run_pipeline,
    run_pipeline_list,
    run_pipeline_resume,
    run_pipeline_show,
    run_pipeline_stages,
)
from .pipeline.orchestrator import PipelineError
from .quality.cli import (
    parse_reference_time,
    quality_database_session,
    run_quality_export,
    run_quality_score,
    run_quality_summary,
)
from .quality.scoring import READINESS, SUBJECT_TYPES
from .refresh.cli import (
    run_refresh_begin,
    run_refresh_changes,
    run_refresh_complete,
    run_refresh_fail,
    run_refresh_record,
    run_refresh_runs,
    run_refresh_show,
)
from .reporting.cli import parse_reference_time as parse_report_reference_time
from .reporting.cli import run_report, run_report_export
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
    run_website_batch_verify,
    run_website_checks,
    run_website_crawl,
    run_website_discover,
    run_website_extract_people,
    run_website_import_manual,
    run_website_list,
    run_website_manual_template,
    run_website_pages,
    run_website_people,
    run_website_populate_candidates,
    run_website_review_decide,
    run_website_review_list,
    run_website_verify,
)
from .verticals.cli import (
    profile_payload,
    profiles_payload,
    run_verticals_assign,
    run_verticals_entities,
    run_verticals_seed,
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

    entity_parser = subparsers.add_parser(
        "entity",
        help="Materialize and inspect resolved entities.",
    )
    entity_subparsers = entity_parser.add_subparsers(
        dest="entity_command",
    )
    entity_subparsers.add_parser(
        "materialize",
        help="Create baseline entities from source records.",
    )

    match_parser = subparsers.add_parser(
        "match",
        help="Generate entity-resolution match candidates.",
    )
    match_subparsers = match_parser.add_subparsers(
        dest="match_command",
    )
    match_subparsers.add_parser(
        "deterministic",
        help="Run deterministic entity matching.",
    )
    match_subparsers.add_parser(
        "fuzzy",
        help="Run fuzzy entity matching.",
    )
    match_subparsers.add_parser(
        "all",
        help="Run deterministic matching followed by fuzzy matching.",
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
    website_manual_parser = website_subparsers.add_parser(
        "import-manual",
        help="Import manually researched website URLs for existing entities offline.",
    )
    website_manual_parser.add_argument(
        "path",
        type=Path,
        help="CSV with entity_id and website_url columns.",
    )
    website_manual_parser.add_argument(
        "--source",
        default="Manual Website Evidence Intake",
        help="Registered manual evidence source name.",
    )
    website_manual_parser.add_argument("--dry-run", action="store_true")
    website_template_parser = website_subparsers.add_parser(
        "manual-template",
        help="Write a deterministic CSV template for entities lacking website candidates.",
    )
    website_template_parser.add_argument("--output", type=Path, required=True)
    website_template_parser.add_argument("--limit", type=int)
    website_populate_parser = website_subparsers.add_parser(
        "populate-candidates",
        help="Populate website candidates offline from trusted source provenance.",
    )
    website_populate_parser.add_argument("--entity-id", type=int)
    website_populate_parser.add_argument("--source-dataset-id", type=int)
    website_populate_parser.add_argument("--entity-limit", type=int, default=10)
    website_populate_parser.add_argument("--candidate-limit", type=int, default=1)
    website_populate_parser.add_argument("--dry-run", action="store_true")
    website_batch_parser = website_subparsers.add_parser(
        "batch-verify",
        help="Verify a bounded candidate batch; requires explicit network authorization.",
    )
    website_batch_parser.add_argument("--allow-network", action="store_true")
    website_batch_parser.add_argument("--dry-run", action="store_true")
    website_batch_parser.add_argument("--entity-id", type=int)
    website_batch_parser.add_argument("--entity-limit", type=int, default=10)
    website_batch_parser.add_argument("--candidate-limit", type=int, default=1)
    website_batch_parser.add_argument("--timeout", type=int, default=10)
    website_batch_parser.add_argument("--max-redirects", type=int, default=5)
    website_batch_parser.add_argument("--max-retries", type=int, default=1)
    website_batch_parser.add_argument("--resume-run-id", type=int)
    website_batch_parser.add_argument("--user-agent", default="CanadaFuneralIntel/0.1")
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

    website_extract_people_parser = website_subparsers.add_parser(
        "extract-people",
        help="Extract conservative page-level people observations.",
    )
    website_extract_people_parser.add_argument(
        "--website-id",
        type=int,
        required=True,
        help="Website candidate ID to extract.",
    )
    website_extract_people_parser.add_argument(
        "--page-id",
        type=int,
        help="Optional discovered page ID to extract.",
    )
    website_extract_people_parser.add_argument(
        "--user-agent",
        default="CanadaFuneralIntel/0.1",
        help="HTTP User-Agent for bounded page fetches.",
    )
    website_extract_people_parser.add_argument(
        "--timeout",
        type=int,
        default=10,
        help="Per-network-operation timeout in seconds (default: 10).",
    )
    website_extract_people_parser.add_argument(
        "--max-redirects",
        type=int,
        default=5,
        help="Maximum redirects per page (default: 5).",
    )

    website_people_parser = website_subparsers.add_parser(
        "people",
        help="List page-level people observations.",
    )
    website_people_parser.add_argument(
        "--website-id",
        type=int,
        help="Optional website candidate ID to filter.",
    )
    website_people_parser.add_argument(
        "--entity-id",
        type=int,
        help="Optional entity ID to filter.",
    )
    website_people_parser.add_argument(
        "--page-id",
        type=int,
        help="Optional discovered page ID to filter.",
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
    website_people_review_parser = website_subparsers.add_parser(
        "people-review", help="Review page-level person observations."
    )
    website_people_review_subparsers = website_people_review_parser.add_subparsers(
        dest="website_people_review_command"
    )
    website_people_review_subparsers.add_parser("populate", help="Queue observations.")
    website_people_review_backlog = website_people_review_subparsers.add_parser(
        "backlog", help="Show read-only person observation workflow backlog."
    )
    website_people_review_backlog.add_argument(
        "--details", action="store_true", help="Include observation IDs and provenance."
    )
    website_people_review_list = website_people_review_subparsers.add_parser(
        "list", help="List observation review entries."
    )
    website_people_review_list.add_argument(
        "--status",
        choices=("pending", "accepted", "rejected", "deferred", "all"),
        default="pending",
    )
    website_people_review_decide = website_people_review_subparsers.add_parser(
        "decide", help="Decide an observation review entry."
    )
    website_people_review_decide.add_argument("--queue-id", required=True, type=int)
    website_people_review_decide.add_argument(
        "--status", required=True, choices=("accepted", "rejected", "deferred")
    )
    website_people_review_decide.add_argument("--note")

    facts_parser = subparsers.add_parser(
        "business-facts", help="Read evidence-backed business fact observations."
    )
    facts_subparsers = facts_parser.add_subparsers(dest="business_facts_command")

    def add_fact_filters(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--entity-id", type=int)
        parser.add_argument("--website-id", type=int)
        parser.add_argument("--page-id", type=int)
        parser.add_argument("--fact-key")

    facts_list_parser = facts_subparsers.add_parser(
        "list", help="List business fact observations."
    )
    add_fact_filters(facts_list_parser)
    facts_summary_parser = facts_subparsers.add_parser(
        "summary", help="Summarize business fact observations."
    )
    add_fact_filters(facts_summary_parser)
    facts_export_parser = facts_subparsers.add_parser(
        "export", help="Export business fact observations."
    )
    facts_export_parser.add_argument("--output", required=True, type=Path)
    add_fact_filters(facts_export_parser)
    facts_extract_parser = facts_subparsers.add_parser(
        "extract",
        help="Re-fetch selected persisted pages and extract business facts.",
    )
    facts_extract_parser.add_argument("--website-id", type=int)
    facts_extract_parser.add_argument("--page-id", type=int)
    facts_extract_parser.add_argument("--user-agent")
    facts_extract_parser.add_argument("--timeout", type=int)
    facts_extract_parser.add_argument("--max-redirects", type=int)

    quality_parser = subparsers.add_parser(
        "quality", help="Read-only quality and confidence reporting."
    )
    quality_subparsers = quality_parser.add_subparsers(dest="quality_command")
    quality_score_parser = quality_subparsers.add_parser(
        "score", help="Score one evidence subject."
    )
    quality_score_parser.add_argument(
        "--subject-type", required=True, choices=SUBJECT_TYPES
    )
    quality_score_parser.add_argument("--subject-id", required=True, type=int)
    quality_score_parser.add_argument("--reference-time")
    quality_score_parser.add_argument("--include-historical", action="store_true")

    def add_quality_filters(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--subject-type", choices=SUBJECT_TYPES, default="entity")
        parser.add_argument("--reference-time")
        parser.add_argument("--readiness", choices=READINESS)
        parser.add_argument("--minimum-score", type=float)
        parser.add_argument("--maximum-score", type=float)
        parser.add_argument("--entity-id", type=int)
        parser.add_argument("--conflict-only", action="store_true")
        parser.add_argument("--incomplete-only", action="store_true")
        parser.add_argument("--include-historical", action="store_true")

    quality_summary_parser = quality_subparsers.add_parser(
        "summary", help="List deterministic quality scores."
    )
    add_quality_filters(quality_summary_parser)
    quality_export_parser = quality_subparsers.add_parser(
        "export", help="Export deterministic quality reports."
    )
    quality_export_parser.add_argument("--output", required=True, type=Path)
    quality_export_parser.add_argument("--reference-time")
    quality_export_parser.add_argument("--include-historical", action="store_true")

    report_parser = subparsers.add_parser(
        "report", help="Read-only aggregate reporting and exports."
    )
    report_subparsers = report_parser.add_subparsers(dest="report_command")
    for report_name in ("coverage", "quality", "business", "people", "summary"):
        item = report_subparsers.add_parser(
            report_name, help=f"Generate the {report_name} report."
        )
        item.add_argument("--reference-time")
        item.add_argument("--include-historical", action="store_true")
    report_export = report_subparsers.add_parser(
        "export", help="Export deterministic report files and manifest."
    )
    report_export.add_argument("--output", required=True, type=Path)
    report_export.add_argument("--reference-time")
    report_export.add_argument("--include-historical", action="store_true")

    refresh_parser = subparsers.add_parser(
        "refresh", help="Manage offline refresh comparisons."
    )
    refresh_subparsers = refresh_parser.add_subparsers(dest="refresh_command")
    refresh_begin = refresh_subparsers.add_parser(
        "begin", help="Begin an offline refresh run."
    )
    refresh_begin.add_argument(
        "--run-type",
        required=True,
        choices=("website_page", "person_observation", "business_fact"),
    )
    refresh_begin.add_argument("--scope-type", required=True)
    refresh_begin.add_argument("--scope-value")
    refresh_begin.add_argument("--reference-time", required=True)
    refresh_begin.add_argument("--extractor-version")
    refresh_begin.add_argument("--config-fingerprint")
    refresh_record = refresh_subparsers.add_parser(
        "record", help="Record one offline observation."
    )
    refresh_record.add_argument("--run-id", required=True, type=int)
    refresh_record.add_argument(
        "--subject-type",
        required=True,
        choices=("website_page", "person_observation", "business_fact"),
    )
    refresh_record.add_argument("--subject-key", required=True)
    refresh_record.add_argument("--fingerprint", required=True)
    refresh_record.add_argument("--reference-id", type=int)
    refresh_record.add_argument("--metadata-json", default="{}")
    refresh_complete = refresh_subparsers.add_parser(
        "complete", help="Complete and compare a refresh run."
    )
    refresh_complete.add_argument("--run-id", required=True, type=int)
    refresh_fail = refresh_subparsers.add_parser(
        "fail", help="Fail or cancel a refresh run."
    )
    refresh_fail.add_argument("--run-id", required=True, type=int)
    refresh_fail.add_argument("--error", required=True)
    refresh_fail.add_argument("--cancelled", action="store_true")
    refresh_runs_parser = refresh_subparsers.add_parser(
        "runs", help="List refresh runs."
    )
    refresh_runs_parser.add_argument(
        "--run-type", choices=("website_page", "person_observation", "business_fact")
    )
    refresh_runs_parser.add_argument(
        "--status", choices=("running", "completed", "failed", "cancelled")
    )
    refresh_show = refresh_subparsers.add_parser("show", help="Show one refresh run.")
    refresh_show.add_argument("--run-id", required=True, type=int)
    refresh_changes_parser = refresh_subparsers.add_parser(
        "changes", help="List immutable change events."
    )
    refresh_changes_parser.add_argument("--run-id", type=int)
    refresh_changes_parser.add_argument(
        "--subject-type",
        choices=("website_page", "person_observation", "business_fact"),
    )
    refresh_changes_parser.add_argument("--subject-key")
    refresh_changes_parser.add_argument(
        "--change-type", choices=("added", "changed", "missing", "reappeared")
    )

    pipeline_parser = subparsers.add_parser(
        "pipeline", help="Run the offline import and entity preparation pipeline."
    )
    pipeline_subparsers = pipeline_parser.add_subparsers(dest="pipeline_command")
    pipeline_run = pipeline_subparsers.add_parser(
        "run", help="Run a local offline pipeline."
    )
    pipeline_run.add_argument("--source", required=True)
    pipeline_run.add_argument("--path", required=True, type=Path)
    pipeline_run.add_argument(
        "--format", required=True, choices=("csv", "json"), dest="input_format"
    )
    pipeline_run.add_argument("--external-id-field")
    pipeline_run.add_argument(
        "--through-stage",
        choices=(
            "import",
            "normalize",
            "deterministic_match",
            "fuzzy_match",
            "review_queue",
            "materialize",
        ),
        default="materialize",
    )
    pipeline_run.add_argument("--skip-fuzzy", action="store_true")
    pipeline_run.add_argument("--dry-run", action="store_true")
    pipeline_resume = pipeline_subparsers.add_parser(
        "resume", help="Resume a failed or cancelled pipeline run."
    )
    pipeline_resume.add_argument("--run-id", required=True, type=int)
    pipeline_show = pipeline_subparsers.add_parser(
        "show", help="Show one pipeline run."
    )
    pipeline_show.add_argument("--run-id", required=True, type=int)
    pipeline_list = pipeline_subparsers.add_parser("list", help="List pipeline runs.")
    pipeline_list.add_argument(
        "--status", choices=("pending", "running", "completed", "failed", "cancelled")
    )
    pipeline_list.add_argument("--limit", type=int)
    pipeline_stages = pipeline_subparsers.add_parser(
        "stages", help="List stages for one pipeline run."
    )
    pipeline_stages.add_argument("--run-id", required=True, type=int)

    verticals_parser = subparsers.add_parser(
        "verticals", help="Inspect and classify business verticals."
    )
    verticals_subparsers = verticals_parser.add_subparsers(dest="verticals_command")
    verticals_subparsers.add_parser("list", help="List vertical profiles.")
    verticals_show = verticals_subparsers.add_parser(
        "show", help="Show one vertical profile."
    )
    verticals_show.add_argument("--vertical", required=True)
    verticals_entities = verticals_subparsers.add_parser(
        "entities", help="List explicit vertical memberships."
    )
    verticals_entities.add_argument("--vertical", required=True)
    verticals_subparsers.add_parser("seed", help="Seed configured vertical profiles.")
    verticals_assign = verticals_subparsers.add_parser(
        "assign", help="Assign an explicit entity vertical membership."
    )
    verticals_assign.add_argument("--entity-id", required=True, type=int)
    verticals_assign.add_argument("--vertical", required=True)
    verticals_assign.add_argument("--actor", required=True)
    verticals_assign.add_argument("--confidence", type=float, default=1.0)
    verticals_assign.add_argument("--source-record-id", type=int)

    people_parser = subparsers.add_parser(
        "people", help="Review and resolve canonical people."
    )
    people_subparsers = people_parser.add_subparsers(dest="people_command")
    people_review_parser = people_subparsers.add_parser(
        "people-review", help="Review page-level person observations."
    )
    people_review_subparsers = people_review_parser.add_subparsers(
        dest="people_review_command"
    )
    people_review_subparsers.add_parser(
        "populate", help="Queue page-level person observations."
    )
    people_review_backlog_parser = people_review_subparsers.add_parser(
        "backlog", help="Show read-only person observation workflow backlog."
    )
    people_review_backlog_parser.add_argument(
        "--details", action="store_true", help="Include observation IDs and provenance."
    )
    people_review_list_parser = people_review_subparsers.add_parser(
        "list", help="List person observation review entries."
    )
    people_review_list_parser.add_argument(
        "--status",
        choices=("pending", "accepted", "rejected", "deferred", "all"),
        default="pending",
    )
    people_review_decide_parser = people_review_subparsers.add_parser(
        "decide", help="Decide a person observation review entry."
    )
    people_review_decide_parser.add_argument("--queue-id", required=True, type=int)
    people_review_decide_parser.add_argument(
        "--status", required=True, choices=("accepted", "rejected", "deferred")
    )
    people_review_decide_parser.add_argument("--note")
    people_list_parser = people_subparsers.add_parser(
        "list", help="List canonical people."
    )
    people_list_parser.add_argument("--entity-id", type=int)
    people_show_parser = people_subparsers.add_parser(
        "show", help="Show one canonical person."
    )
    people_show_parser.add_argument("--person-id", required=True, type=int)
    people_resolve_parser = people_subparsers.add_parser(
        "resolve", help="Resolve an accepted observation explicitly."
    )
    people_resolve_parser.add_argument("--observation-id", required=True, type=int)
    people_merge_parser = people_subparsers.add_parser(
        "merge", help="Merge two canonical people explicitly."
    )
    people_merge_parser.add_argument("--survivor-person-id", required=True, type=int)
    people_merge_parser.add_argument("--absorbed-person-id", required=True, type=int)
    people_merge_parser.add_argument("--reason", required=True)
    people_rollback_parser = people_subparsers.add_parser(
        "rollback", help="Roll back a canonical person merge."
    )
    people_rollback_parser.add_argument("--merge-id", required=True, type=int)
    people_rollback_parser.add_argument("--reason", required=True)
    people_audit_parser = people_subparsers.add_parser(
        "audit", help="Audit one canonical person and its provenance."
    )
    people_audit_parser.add_argument("--person-id", required=True, type=int)
    people_audit_list_parser = people_subparsers.add_parser(
        "audit-list", help="List canonical person audit summaries."
    )
    people_audit_list_parser.add_argument("--include-historical", action="store_true")
    people_export_parser = people_subparsers.add_parser(
        "export", help="Export canonical person audit data."
    )
    people_export_parser.add_argument("--format", required=True, choices=("csv",))
    people_export_parser.add_argument("--output", required=True, type=Path)
    people_export_parser.add_argument("--include-historical", action="store_true")

    def add_triage_options(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--person-id", type=int)
        parser.add_argument("--anomaly")
        parser.add_argument(
            "--severity", choices=tuple(item.value for item in TriageSeverity)
        )
        parser.add_argument(
            "--traceability", choices=("traceable", "incomplete", "orphaned")
        )
        parser.add_argument("--entity-id", type=int)
        parser.add_argument("--branch-id", type=int)
        parser.add_argument("--website-id", type=int)
        parser.add_argument("--page-id", type=int)
        parser.add_argument(
            "--review-status", choices=("pending", "accepted", "rejected", "deferred")
        )
        parser.add_argument(
            "--disposition-status",
            choices=tuple(item.value for item in DispositionStatus),
        )
        parser.add_argument("--unreviewed-only", action="store_true")
        parser.add_argument("--has-remediation", action="store_true")
        parser.add_argument("--no-remediation", action="store_true")
        parser.add_argument(
            "--remediation-status",
            choices=tuple(item.value for item in RemediationStatus),
        )
        parser.add_argument("--remediation-owner")
        parser.add_argument("--overdue-remediation", action="store_true")
        parser.add_argument("--has-email", action="store_true")
        parser.add_argument("--has-phone", action="store_true")
        parser.add_argument("--include-historical", action="store_true")
        parser.add_argument("--limit", type=int)

    people_triage_parser = people_subparsers.add_parser(
        "triage", help="Show read-only anomaly triage."
    )
    add_triage_options(people_triage_parser)
    people_triage_queue_parser = people_subparsers.add_parser(
        "triage-queue", help="List ranked read-only anomaly triage."
    )
    add_triage_options(people_triage_queue_parser)
    anomaly_review_parser = people_subparsers.add_parser(
        "anomaly-review", help="Review durable person anomaly dispositions."
    )
    anomaly_review_subparsers = anomaly_review_parser.add_subparsers(
        dest="anomaly_review_command"
    )
    anomaly_list_parser = anomaly_review_subparsers.add_parser(
        "list", help="List anomaly dispositions."
    )
    anomaly_list_parser.add_argument("--person-id", type=int)
    anomaly_list_parser.add_argument("--anomaly")
    anomaly_list_parser.add_argument(
        "--status", choices=tuple(item.value for item in DispositionStatus)
    )
    anomaly_list_parser.add_argument("--include-stale", action="store_true")
    anomaly_list_parser.add_argument("--actor")
    anomaly_list_parser.add_argument("--limit", type=int)
    anomaly_show_parser = anomaly_review_subparsers.add_parser(
        "show", help="Show one anomaly disposition."
    )
    anomaly_show_parser.add_argument("--disposition-id", required=True, type=int)
    anomaly_history_parser = anomaly_review_subparsers.add_parser(
        "history", help="Show disposition history."
    )
    anomaly_history_parser.add_argument("--disposition-id", required=True, type=int)
    anomaly_decide_parser = anomaly_review_subparsers.add_parser(
        "decide", help="Apply a disposition decision to an exact anomaly."
    )
    anomaly_decide_parser.add_argument("--person-id", required=True, type=int)
    anomaly_decide_parser.add_argument("--anomaly", required=True)
    anomaly_decide_parser.add_argument("--fingerprint", required=True)
    anomaly_decide_parser.add_argument(
        "--status", required=True, choices=("acknowledged", "dismissed", "reopened")
    )
    anomaly_decide_parser.add_argument("--actor", required=True)
    anomaly_decide_parser.add_argument("--note")
    anomaly_sync_parser = people_subparsers.add_parser(
        "anomaly-sync", help="Mark changed dispositions stale."
    )
    anomaly_sync_parser.add_argument("--person-id", type=int)
    anomaly_sync_parser.add_argument("--actor", default="anomaly-sync")
    remediation_parser = people_subparsers.add_parser(
        "remediation", help="Manage manual person anomaly remediation tasks."
    )
    remediation_subparsers = remediation_parser.add_subparsers(
        dest="remediation_command"
    )
    remediation_list = remediation_subparsers.add_parser(
        "list", help="List remediation tasks."
    )
    remediation_list.add_argument("--person-id", type=int)
    remediation_list.add_argument("--anomaly")
    remediation_list.add_argument("--fingerprint")
    remediation_list.add_argument(
        "--status", choices=tuple(item.value for item in RemediationStatus)
    )
    remediation_list.add_argument("--owner")
    remediation_list.add_argument("--task-type", choices=TASK_TYPES)
    remediation_list.add_argument("--due-before")
    remediation_list.add_argument("--due-after")
    remediation_list.add_argument("--include-stale", action="store_true")
    remediation_list.add_argument("--overdue-only", action="store_true")
    remediation_list.add_argument("--limit", type=int)
    remediation_show = remediation_subparsers.add_parser(
        "show", help="Show one remediation task."
    )
    remediation_show.add_argument("--task-id", required=True, type=int)
    remediation_history = remediation_subparsers.add_parser(
        "history", help="Show remediation task history."
    )
    remediation_history.add_argument("--task-id", required=True, type=int)
    remediation_create = remediation_subparsers.add_parser(
        "create", help="Create a manual remediation task."
    )
    remediation_create.add_argument("--person-id", required=True, type=int)
    remediation_create.add_argument("--anomaly", required=True)
    remediation_create.add_argument("--fingerprint", required=True)
    remediation_create.add_argument("--task-type", required=True, choices=TASK_TYPES)
    remediation_create.add_argument("--actor", required=True)
    remediation_create.add_argument("--owner")
    remediation_create.add_argument("--due-at")
    remediation_create.add_argument("--note")
    remediation_update = remediation_subparsers.add_parser(
        "update", help="Update a remediation task."
    )
    remediation_update.add_argument("--task-id", required=True, type=int)
    remediation_update.add_argument(
        "--status",
        choices=tuple(
            item.value
            for item in RemediationStatus
            if item is not RemediationStatus.STALE
        ),
    )
    remediation_update.add_argument("--actor", required=True)
    remediation_update.add_argument("--owner")
    remediation_update.add_argument("--clear-owner", action="store_true")
    remediation_update.add_argument("--due-at")
    remediation_update.add_argument("--clear-due-at", action="store_true")
    remediation_update.add_argument("--note")
    remediation_sync_parser = people_subparsers.add_parser(
        "remediation-sync", help="Mark changed remediation tasks stale."
    )
    remediation_sync_parser.add_argument("--person-id", type=int)
    remediation_sync_parser.add_argument("--actor", default="remediation-sync")
    work_queue_parser = people_subparsers.add_parser(
        "work-queue", help="Show the read-only reviewer operations queue."
    )
    work_queue_subparsers = work_queue_parser.add_subparsers(dest="work_queue_command")

    def add_work_queue_filters(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--person-id", type=int)
        parser.add_argument("--entity-id", type=int)
        parser.add_argument("--anomaly")
        parser.add_argument("--severity", choices=("critical", "high", "medium", "low"))
        parser.add_argument(
            "--traceability", choices=("traceable", "incomplete", "orphaned")
        )
        parser.add_argument("--disposition-status")
        parser.add_argument("--queue-state")
        parser.add_argument("--owner")
        parser.add_argument("--unassigned-only", action="store_true")
        parser.add_argument("--has-remediation", action="store_true")
        parser.add_argument("--no-remediation", action="store_true")
        parser.add_argument("--overdue-only", action="store_true")
        parser.add_argument("--blocked-only", action="store_true")
        parser.add_argument("--stale-only", action="store_true")
        parser.add_argument("--include-stale", action="store_true")
        parser.add_argument("--include-historical", action="store_true")
        parser.add_argument("--due-before")
        parser.add_argument("--due-after")
        parser.add_argument("--limit", type=int)

    work_queue_list_parser = work_queue_subparsers.add_parser(
        "list", help="List current reviewer work."
    )
    add_work_queue_filters(work_queue_list_parser)
    work_queue_show_parser = work_queue_subparsers.add_parser(
        "show", help="Show one exact current anomaly work item."
    )
    work_queue_show_parser.add_argument("--person-id", required=True, type=int)
    work_queue_show_parser.add_argument("--fingerprint", required=True)
    work_queue_show_parser.add_argument("--include-historical", action="store_true")
    work_queue_owners_parser = work_queue_subparsers.add_parser(
        "owners", help="Summarize persisted remediation ownership."
    )
    work_queue_owners_parser.add_argument("--include-historical", action="store_true")
    work_queue_export_parser = work_queue_subparsers.add_parser(
        "export", help="Export the read-only reviewer work queue."
    )
    work_queue_export_parser.add_argument("--output", required=True, type=Path)
    work_queue_export_parser.add_argument("--include-historical", action="store_true")

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

    if args.command == "business-facts":
        if args.business_facts_command is None:
            parser.parse_args(["business-facts", "--help"])
            return 2
        try:
            with database_session(settings.database_path) as connection:
                if args.business_facts_command == "extract":
                    payload = run_business_facts_extract(
                        connection,
                        website_id=args.website_id,
                        page_id=args.page_id,
                        user_agent=args.user_agent or settings.http_user_agent,
                        timeout_seconds=(
                            args.timeout
                            if args.timeout is not None
                            else settings.http_timeout_seconds
                        ),
                        max_redirects=(
                            args.max_redirects if args.max_redirects is not None else 5
                        ),
                    )
                else:
                    filters = {
                        "entity_id": args.entity_id,
                        "website_id": args.website_id,
                        "page_id": args.page_id,
                        "fact_key": args.fact_key,
                    }
                    if args.business_facts_command == "list":
                        payload = run_business_facts_list(connection, **filters)
                    elif args.business_facts_command == "summary":
                        payload = run_business_facts_summary(connection, **filters)
                    elif args.business_facts_command == "export":
                        payload = run_business_facts_export(
                            connection, output=args.output, **filters
                        )
                    else:
                        parser.parse_args(["business-facts", "--help"])
                        return 2
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0
        except (DatabaseError, BusinessFactCommandError) as exc:
            print(f"business facts error: {exc}", file=sys.stderr)
            return 18

    if args.command == "quality":
        if args.quality_command is None:
            parser.parse_args(["quality", "--help"])
            return 2
        try:
            reference_time = parse_reference_time(args.reference_time)
            with quality_database_session(settings.database_path) as connection:
                if args.quality_command == "score":
                    payload = run_quality_score(
                        connection,
                        subject_type=args.subject_type,
                        subject_id=args.subject_id,
                        reference_time=reference_time,
                        include_historical=args.include_historical,
                    )
                elif args.quality_command == "summary":
                    payload = run_quality_summary(
                        connection,
                        subject_type=args.subject_type,
                        reference_time=reference_time,
                        include_historical=args.include_historical,
                        readiness=args.readiness,
                        minimum_score=args.minimum_score,
                        maximum_score=args.maximum_score,
                        entity_id=args.entity_id,
                        conflict_only=args.conflict_only,
                        incomplete_only=args.incomplete_only,
                    )
                elif args.quality_command == "export":
                    payload = run_quality_export(
                        connection,
                        output=args.output,
                        reference_time=reference_time,
                        include_historical=args.include_historical,
                    )
                else:
                    parser.parse_args(["quality", "--help"])
                    return 2
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0
        except (DatabaseError, ValueError) as exc:
            print(f"quality error: {exc}", file=sys.stderr)
            return 13

    if args.command == "report":
        if args.report_command is None:
            parser.parse_args(["report", "--help"])
            return 2
        try:
            reference_time = parse_report_reference_time(args.reference_time)
            with quality_database_session(settings.database_path) as connection:
                payload = (
                    run_report_export(
                        connection,
                        output=args.output,
                        include_historical=args.include_historical,
                        reference_time=reference_time,
                    )
                    if args.report_command == "export"
                    else run_report(
                        connection,
                        args.report_command,
                        include_historical=args.include_historical,
                        reference_time=reference_time,
                    )
                )
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0
        except (DatabaseError, ValueError) as exc:
            print(f"report error: {exc}", file=sys.stderr)
            return 14

    if args.command == "refresh":
        if args.refresh_command is None:
            parser.parse_args(["refresh", "--help"])
            return 2
        try:
            with database_session(settings.database_path) as connection:
                if args.refresh_command == "begin":
                    payload = run_refresh_begin(
                        connection,
                        run_type=args.run_type,
                        scope_type=args.scope_type,
                        scope_value=args.scope_value,
                        reference_time=parse_report_reference_time(args.reference_time),
                        extractor_version=args.extractor_version,
                        config_fingerprint=args.config_fingerprint,
                    )
                elif args.refresh_command == "record":
                    payload = run_refresh_record(
                        connection,
                        run_id=args.run_id,
                        subject_type=args.subject_type,
                        subject_key=args.subject_key,
                        semantic_fingerprint=args.fingerprint,
                        reference_id=args.reference_id,
                        metadata_json=args.metadata_json,
                    )
                elif args.refresh_command == "complete":
                    payload = run_refresh_complete(connection, args.run_id)
                elif args.refresh_command == "fail":
                    payload = run_refresh_fail(
                        connection,
                        run_id=args.run_id,
                        error_summary=args.error,
                        status="cancelled" if args.cancelled else "failed",
                    )
                elif args.refresh_command == "runs":
                    payload = run_refresh_runs(
                        connection, run_type=args.run_type, status=args.status
                    )
                elif args.refresh_command == "show":
                    payload = run_refresh_show(connection, args.run_id)
                elif args.refresh_command == "changes":
                    payload = run_refresh_changes(
                        connection,
                        run_id=args.run_id,
                        subject_type=args.subject_type,
                        subject_key=args.subject_key,
                        change_type=args.change_type,
                    )
                else:
                    parser.parse_args(["refresh", "--help"])
                    return 2
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0
        except (DatabaseError, ValueError) as exc:
            print(f"refresh error: {exc}", file=sys.stderr)
            return 15

    if args.command == "pipeline":
        if args.pipeline_command is None:
            parser.parse_args(["pipeline", "--help"])
            return 2
        try:
            with database_session(settings.database_path) as connection:
                if args.pipeline_command == "run":
                    payload = run_pipeline(
                        connection,
                        source_name=args.source,
                        input_path=args.path,
                        input_format=ImportFormat(args.input_format),
                        external_id_field=args.external_id_field,
                        through_stage=args.through_stage,
                        skip_fuzzy=args.skip_fuzzy,
                        dry_run=args.dry_run,
                    )
                elif args.pipeline_command == "resume":
                    payload = run_pipeline_resume(connection, args.run_id)
                elif args.pipeline_command == "show":
                    payload = run_pipeline_show(connection, args.run_id)
                elif args.pipeline_command == "list":
                    payload = run_pipeline_list(
                        connection, status=args.status, limit=args.limit
                    )
                elif args.pipeline_command == "stages":
                    payload = run_pipeline_stages(connection, args.run_id)
                else:
                    parser.parse_args(["pipeline", "--help"])
                    return 2
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0
        except (DatabaseError, PipelineError, ValueError) as exc:
            print(f"pipeline error: {exc}", file=sys.stderr)
            return 17

    if args.command == "verticals":
        if args.verticals_command is None:
            parser.parse_args(["verticals", "--help"])
            return 2
        try:
            if args.verticals_command == "list":
                payload = profiles_payload()
            elif args.verticals_command == "show":
                payload = profile_payload(args.vertical)
            else:
                with database_session(settings.database_path) as connection:
                    if args.verticals_command == "seed":
                        payload = run_verticals_seed(connection)
                    elif args.verticals_command == "entities":
                        payload = run_verticals_entities(connection, args.vertical)
                    elif args.verticals_command == "assign":
                        payload = run_verticals_assign(
                            connection,
                            entity_id=args.entity_id,
                            vertical_key=args.vertical,
                            actor=args.actor,
                            confidence=args.confidence,
                            source_record_id=args.source_record_id,
                        )
                    else:
                        parser.parse_args(["verticals", "--help"])
                        return 2
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0
        except (DatabaseError, ValueError) as exc:
            print(f"verticals error: {exc}", file=sys.stderr)
            return 16

    if args.command == "sources" and args.sources_command == "collect":
        from canada_funeral_intel.collectors.british_columbia_cli import (
            BritishColumbiaCollectCommandError,
            run_british_columbia_collect_command,
        )
        from canada_funeral_intel.collectors.manitoba_cli import (
            ManitobaCollectCommandError,
            run_manitoba_collect_command,
        )
        from canada_funeral_intel.collectors.quebec_cli import (
            QuebecCollectCommandError,
            run_quebec_collect_command,
        )
        from canada_funeral_intel.collectors.saskatchewan_cli import (
            SaskatchewanCollectCommandError,
            run_saskatchewan_collect_command,
        )

        try:
            timeout_seconds = (
                args.timeout
                if args.timeout is not None
                else settings.http_timeout_seconds
            )
            with database_session(settings.database_path) as connection:
                if (
                    args.name.casefold()
                    == "consumer protection bc funeral services register"
                ):
                    payload = run_british_columbia_collect_command(
                        connection,
                        migration_dir=_MIGRATION_DIR,
                        registry_path=_SOURCE_REGISTRY_PATH,
                        source_name=args.name,
                        user_agent=settings.http_user_agent,
                        timeout_seconds=timeout_seconds,
                    )
                elif (
                    args.name.casefold()
                    == "funeral and cremation services council of saskatchewan roster"
                ):
                    payload = run_saskatchewan_collect_command(
                        connection,
                        migration_dir=_MIGRATION_DIR,
                        registry_path=_SOURCE_REGISTRY_PATH,
                        source_name=args.name,
                        user_agent=settings.http_user_agent,
                        timeout_seconds=timeout_seconds,
                    )
                elif (
                    args.name.casefold()
                    == "santé québec funeral services permit directory"
                ):
                    payload = run_quebec_collect_command(
                        connection,
                        migration_dir=_MIGRATION_DIR,
                        registry_path=_SOURCE_REGISTRY_PATH,
                        source_name=args.name,
                        user_agent=settings.http_user_agent,
                        timeout_seconds=timeout_seconds,
                    )
                else:
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
        except (
            DatabaseError,
            ManitobaCollectCommandError,
            BritishColumbiaCollectCommandError,
            SaskatchewanCollectCommandError,
            QuebecCollectCommandError,
        ) as exc:
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

    if args.command == "entity":
        if args.entity_command is None:
            parser.parse_args(["entity", "--help"])
            return 2

        try:
            with database_session(settings.database_path) as connection:
                if args.entity_command == "materialize":
                    payload = run_entity_materialize(connection)
                else:
                    parser.parse_args(["entity", "--help"])
                    return 2

            print_entity_payload(payload)
            return 0
        except (
            DatabaseError,
            EntityCommandError,
        ) as exc:
            print(
                f"entity error: {exc}",
                file=sys.stderr,
            )
            return 11

    if args.command == "match":
        if args.match_command is None:
            parser.parse_args(["match", "--help"])
            return 2

        try:
            with database_session(settings.database_path) as connection:
                payload = run_match_command(
                    connection,
                    mode=MatchMode(args.match_command),
                )
            print_match_payload(payload)
            return 0
        except (DatabaseError, MatchCommandError) as exc:
            print(f"match error: {exc}", file=sys.stderr)
            return 10

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

    if args.command == "people":
        if args.people_command is None:
            parser.parse_args(["people", "--help"])
            return 2
        try:
            with database_session(settings.database_path) as connection:
                if args.people_command == "people-review":
                    if args.people_review_command == "populate":
                        payload = run_people_review_populate(connection)
                    elif args.people_review_command == "backlog":
                        payload = run_people_review_backlog(
                            connection, include_details=args.details
                        )
                    elif args.people_review_command == "list":
                        status = (
                            None
                            if args.status == "all"
                            else PersonReviewStatus(args.status)
                        )
                        payload = run_people_review_list(connection, status)
                    elif args.people_review_command == "decide":
                        payload = run_people_review_decide(
                            connection,
                            queue_id=args.queue_id,
                            status=PersonReviewStatus(args.status),
                            note=args.note,
                        )
                    else:
                        parser.parse_args(["people", "people-review", "--help"])
                        return 2
                elif args.people_command == "list":
                    payload = run_people_list(connection, args.entity_id)
                elif args.people_command == "show":
                    payload = run_people_show(connection, args.person_id)
                elif args.people_command == "resolve":
                    payload = run_people_resolve(connection, args.observation_id)
                elif args.people_command == "merge":
                    payload = run_people_merge(
                        connection,
                        survivor_person_id=args.survivor_person_id,
                        absorbed_person_id=args.absorbed_person_id,
                        reason=args.reason,
                    )
                elif args.people_command == "rollback":
                    payload = run_people_rollback(
                        connection, merge_id=args.merge_id, reason=args.reason
                    )
                elif args.people_command == "audit":
                    payload = run_people_audit(connection, args.person_id)
                elif args.people_command == "audit-list":
                    payload = run_people_audit_list(
                        connection, include_historical=args.include_historical
                    )
                elif args.people_command == "export":
                    payload = run_people_export(
                        connection,
                        output=args.output,
                        include_historical=args.include_historical,
                    )
                elif args.people_command in {"triage", "triage-queue"}:
                    payload = run_people_triage(
                        connection,
                        TriageFilters(
                            person_id=args.person_id,
                            anomaly=args.anomaly,
                            severity=None
                            if args.severity is None
                            else TriageSeverity(args.severity),
                            traceability=args.traceability,
                            entity_id=args.entity_id,
                            branch_id=args.branch_id,
                            website_id=args.website_id,
                            page_id=args.page_id,
                            review_status=args.review_status,
                            disposition_status=None
                            if args.disposition_status is None
                            else DispositionStatus(args.disposition_status),
                            unreviewed_only=args.unreviewed_only,
                            has_remediation=args.has_remediation,
                            no_remediation=args.no_remediation,
                            remediation_status=args.remediation_status,
                            remediation_owner=args.remediation_owner,
                            overdue_remediation=args.overdue_remediation,
                            has_email=args.has_email,
                            has_phone=args.has_phone,
                            include_historical=args.include_historical,
                            limit=args.limit,
                        ),
                    )
                elif args.people_command == "anomaly-review":
                    if args.anomaly_review_command == "list":
                        payload = run_anomaly_review_list(
                            connection,
                            person_id=args.person_id,
                            anomaly_code=args.anomaly,
                            status=None
                            if args.status is None
                            else DispositionStatus(args.status),
                            include_stale=args.include_stale,
                            actor=args.actor,
                            limit=args.limit,
                        )
                    elif args.anomaly_review_command == "show":
                        payload = run_anomaly_review_show(
                            connection, args.disposition_id
                        )
                    elif args.anomaly_review_command == "history":
                        payload = run_anomaly_review_history(
                            connection, args.disposition_id
                        )
                    elif args.anomaly_review_command == "decide":
                        payload = run_anomaly_review_decide(
                            connection,
                            person_id=args.person_id,
                            anomaly_code=args.anomaly,
                            fingerprint=args.fingerprint,
                            status=DispositionStatus(args.status),
                            actor=args.actor,
                            note=args.note,
                        )
                    else:
                        parser.parse_args(["people", "anomaly-review", "--help"])
                        return 2
                elif args.people_command == "anomaly-sync":
                    payload = run_anomaly_sync(
                        connection, person_id=args.person_id, actor=args.actor
                    )
                elif args.people_command == "remediation":
                    if args.remediation_command == "list":
                        payload = run_remediation_list(
                            connection,
                            person_id=args.person_id,
                            anomaly_code=args.anomaly,
                            fingerprint=args.fingerprint,
                            status=None
                            if args.status is None
                            else RemediationStatus(args.status),
                            owner=args.owner,
                            task_type=args.task_type,
                            due_before=args.due_before,
                            due_after=args.due_after,
                            include_stale=args.include_stale,
                            overdue_only=args.overdue_only,
                            limit=args.limit,
                        )
                    elif args.remediation_command == "show":
                        payload = run_remediation_show(connection, args.task_id)
                    elif args.remediation_command == "history":
                        payload = run_remediation_history(connection, args.task_id)
                    elif args.remediation_command == "create":
                        payload = run_remediation_create(
                            connection,
                            person_id=args.person_id,
                            anomaly_code=args.anomaly,
                            fingerprint=args.fingerprint,
                            task_type=args.task_type,
                            actor=args.actor,
                            owner=args.owner,
                            due_at=args.due_at,
                            note=args.note,
                        )
                    elif args.remediation_command == "update":
                        payload = run_remediation_update(
                            connection,
                            task_id=args.task_id,
                            status=None
                            if args.status is None
                            else RemediationStatus(args.status),
                            actor=args.actor,
                            owner=args.owner,
                            clear_owner=args.clear_owner,
                            due_at=args.due_at,
                            clear_due_at=args.clear_due_at,
                            note=args.note,
                        )
                    else:
                        parser.parse_args(["people", "remediation", "--help"])
                        return 2
                elif args.people_command == "remediation-sync":
                    payload = run_remediation_sync(
                        connection, person_id=args.person_id, actor=args.actor
                    )
                elif args.people_command == "work-queue":
                    if args.work_queue_command == "list":
                        payload = run_work_queue_list(
                            connection,
                            WorkQueueFilters(
                                person_id=args.person_id,
                                entity_id=args.entity_id,
                                anomaly=args.anomaly,
                                severity=args.severity,
                                traceability=args.traceability,
                                disposition_status=args.disposition_status,
                                queue_state=args.queue_state,
                                owner=args.owner,
                                unassigned_only=args.unassigned_only,
                                has_remediation=args.has_remediation,
                                no_remediation=args.no_remediation,
                                overdue_only=args.overdue_only,
                                blocked_only=args.blocked_only,
                                stale_only=args.stale_only,
                                include_stale=args.include_stale,
                                include_historical=args.include_historical,
                                due_before=args.due_before,
                                due_after=args.due_after,
                                limit=args.limit,
                            ),
                        )
                    elif args.work_queue_command == "show":
                        payload = run_work_queue_show(
                            connection,
                            person_id=args.person_id,
                            fingerprint=args.fingerprint,
                            include_historical=args.include_historical,
                        )
                    elif args.work_queue_command == "owners":
                        payload = run_work_queue_owners(
                            connection, include_historical=args.include_historical
                        )
                    elif args.work_queue_command == "export":
                        payload = run_work_queue_export(
                            connection,
                            output=args.output,
                            include_historical=args.include_historical,
                        )
                    else:
                        parser.parse_args(["people", "work-queue", "--help"])
                        return 2
                else:
                    parser.parse_args(["people", "--help"])
                    return 2
            print_people_payload(payload)
            return 0
        except (DatabaseError, PeopleCommandError) as exc:
            print(f"people error: {exc}", file=sys.stderr)
            return 12

    if args.command == "website":
        if args.website_command is None:
            parser.parse_args(["website", "--help"])
            return 2

        try:
            with database_session(settings.database_path) as connection:
                if args.website_command == "populate-candidates":
                    payload = run_website_populate_candidates(
                        connection,
                        entity_id=args.entity_id,
                        source_dataset_id=args.source_dataset_id,
                        entity_limit=args.entity_limit,
                        candidate_limit=args.candidate_limit,
                        dry_run=args.dry_run,
                    )

                elif args.website_command == "import-manual":
                    apply_pending_migrations(connection, _MIGRATION_DIR)
                    registry = load_source_registry(_SOURCE_REGISTRY_PATH)
                    seed_source_registry(connection, registry)
                    connection.commit()
                    source = next(
                        (
                            item
                            for item in registry
                            if item.name.casefold() == args.source.casefold()
                        ),
                        None,
                    )
                    if source is None:
                        raise WebsiteCommandError(f"Source not found: {args.source}")
                    source_row = connection.execute(
                        "SELECT id FROM source_datasets WHERE name = ?",
                        (source.name,),
                    ).fetchone()
                    if source_row is None:
                        raise WebsiteCommandError(
                            f"Source registry seed failed for: {source.name}"
                        )
                    payload = run_website_import_manual(
                        connection,
                        input_path=args.path,
                        source_dataset_id=int(source_row["id"]),
                        dry_run=args.dry_run,
                    )

                elif args.website_command == "manual-template":
                    apply_pending_migrations(connection, _MIGRATION_DIR)
                    payload = run_website_manual_template(
                        connection,
                        output_path=args.output,
                        limit=args.limit,
                    )

                elif args.website_command == "batch-verify":
                    payload = run_website_batch_verify(
                        connection,
                        allow_network=args.allow_network,
                        entity_id=args.entity_id,
                        entity_limit=args.entity_limit,
                        candidate_limit=args.candidate_limit,
                        timeout_seconds=args.timeout,
                        max_redirects=args.max_redirects,
                        max_retries=args.max_retries,
                        resume_run_id=args.resume_run_id,
                        user_agent=args.user_agent,
                        dry_run=args.dry_run,
                    )

                elif args.website_command == "discover":
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

                elif args.website_command == "extract-people":
                    payload = run_website_extract_people(
                        connection,
                        website_id=args.website_id,
                        page_id=args.page_id,
                        user_agent=args.user_agent,
                        timeout_seconds=args.timeout,
                        max_redirects=args.max_redirects,
                    )

                elif args.website_command == "people":
                    payload = run_website_people(
                        connection,
                        website_id=args.website_id,
                        entity_id=args.entity_id,
                        page_id=args.page_id,
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

                elif args.website_command == "people-review":
                    if args.website_people_review_command == "populate":
                        payload = run_people_review_populate(connection)
                    elif args.website_people_review_command == "backlog":
                        payload = run_people_review_backlog(
                            connection, include_details=args.details
                        )
                    elif args.website_people_review_command == "list":
                        status = (
                            None
                            if args.status == "all"
                            else PersonReviewStatus(args.status)
                        )
                        payload = run_people_review_list(connection, status)
                    elif args.website_people_review_command == "decide":
                        payload = run_people_review_decide(
                            connection,
                            queue_id=args.queue_id,
                            status=PersonReviewStatus(args.status),
                            note=args.note,
                        )
                    else:
                        parser.parse_args(["website", "people-review", "--help"])
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
