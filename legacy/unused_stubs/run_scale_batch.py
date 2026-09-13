#!/usr/bin/env python3

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_BATCH_ROOT = ROOT / "data" / "generated" / "batches"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def json_count(path):
    if not path.exists():
        return None

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    if isinstance(value, list):
        return len(value)

    if isinstance(value, dict):
        leads = value.get("leads")
        if isinstance(leads, list):
            return len(leads)

    return None


def source_signature(specs):
    digest = hashlib.sha256()

    normalized = []

    for spec in specs:
        if "=" not in spec:
            raise ValueError(
                f"Invalid --source {spec!r}; expected TYPE=PATH"
            )

        source_type, raw_path = spec.split("=", 1)
        source_type = source_type.strip()
        path = Path(raw_path).expanduser().resolve()

        if not source_type:
            raise ValueError(f"Missing source type in {spec!r}")

        if not path.is_file():
            raise ValueError(f"Source file does not exist: {path}")

        file_hash = hashlib.sha256(path.read_bytes()).hexdigest()

        normalized.append(
            {
                "type": source_type,
                "path": str(path),
                "sha256": file_hash,
            }
        )

    for item in sorted(
        normalized,
        key=lambda value: (value["type"], value["path"]),
    ):
        digest.update(item["type"].encode())
        digest.update(b"\0")
        digest.update(item["path"].encode())
        digest.update(b"\0")
        digest.update(item["sha256"].encode())
        digest.update(b"\0")

    return digest.hexdigest(), normalized


def run_command(command, *, stage, manifest_path, manifest):
    print()
    print(f"===== {stage.upper()} =====")
    print("+", " ".join(str(part) for part in command), flush=True)

    manifest["stages"].setdefault(stage, {})
    manifest["stages"][stage].update(
        {
            "status": "running",
            "started_at": utc_now(),
            "command": [str(part) for part in command],
        }
    )
    atomic_json(manifest_path, manifest)

    completed = subprocess.run(
        [str(part) for part in command],
        cwd=ROOT,
    )

    manifest["stages"][stage]["returncode"] = completed.returncode
    manifest["stages"][stage]["finished_at"] = utc_now()

    if completed.returncode == 0:
        manifest["stages"][stage]["status"] = "complete"
    else:
        manifest["stages"][stage]["status"] = "failed"

    atomic_json(manifest_path, manifest)

    return completed.returncode


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Run an isolated restartable funeral-home discovery, crawl, "
            "scoring, and enrichment batch."
        )
    )

    parser.add_argument(
        "--source",
        action="append",
        required=True,
        metavar="TYPE=PATH",
        help=(
            "Discovery source. Repeat for multiple inputs. "
            "Accepted types are controlled by discovery_import.py."
        ),
    )
    parser.add_argument(
        "--batch-root",
        type=Path,
        default=DEFAULT_BATCH_ROOT,
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=15,
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=12,
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=12,
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.25,
    )
    parser.add_argument(
        "--skip-enrichment",
        action="store_true",
    )

    args = parser.parse_args(argv)

    if args.workers < 1:
        parser.error("--workers must be at least 1")

    try:
        signature, sources = source_signature(args.source)
    except ValueError as exc:
        parser.error(str(exc))

    batch_id = signature[:16]
    batch_root = args.batch_root.expanduser().resolve()
    workspace = batch_root / batch_id
    workspace.mkdir(parents=True, exist_ok=True)

    queue = workspace / "crawl_queue.json"
    pages = workspace / "pages.json"
    crawl_report = workspace / "crawl_report.json"
    scored = workspace / "scored_results.json"
    enriched = workspace / "enriched_results.json"
    state = workspace / "agent_state.json"
    audit = workspace / "agent_audit.json"
    review = workspace / "review_queue.json"
    manifest_path = workspace / "batch_manifest.json"

    manifest = {
        "schema_version": 1,
        "batch_id": batch_id,
        "source_signature": signature,
        "sources": sources,
        "workspace": str(workspace),
        "workers": args.workers,
        "updated_at": utc_now(),
        "stages": {},
    }

    if manifest_path.exists():
        try:
            previous = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )
        except Exception as exc:
            print(
                f"STOP: existing batch manifest is unreadable: {exc}",
                file=sys.stderr,
            )
            return 2

        if previous.get("source_signature") != signature:
            print(
                "STOP: existing workspace has a different source signature",
                file=sys.stderr,
            )
            return 2

        manifest["stages"] = previous.get("stages", {})

    atomic_json(manifest_path, manifest)

    print("===== FAST SCALE BATCH =====")
    print(f"batch id:  {batch_id}")
    print(f"workspace: {workspace}")
    print(f"workers:   {args.workers}")
    print()
    print(
        "Same source content produces the same batch ID; "
        "rerunning this command resumes this workspace."
    )

    import_command = [
        sys.executable,
        ROOT / "discovery_import.py",
    ]

    for item in sources:
        import_command.extend(
            [
                "--source",
                f'{item["type"]}={item["path"]}',
            ]
        )

    import_command.extend(["--output", queue])

    rc = run_command(
        import_command,
        stage="discovery",
        manifest_path=manifest_path,
        manifest=manifest,
    )
    if rc:
        print("STOP: discovery import failed")
        return rc

    print(f"queue rows: {json_count(queue)}")

    crawl_command = [
        sys.executable,
        ROOT / "website_crawler.py",
        "--input",
        queue,
        "--output",
        pages,
        "--report-output",
        crawl_report,
        "--append",
        "--resume",
        "--workers",
        str(args.workers),
        "--timeout",
        str(args.timeout),
        "--max-pages",
        str(args.max_pages),
        "--max-attempts",
        str(args.max_attempts),
        "--delay",
        str(args.delay),
    ]

    rc = run_command(
        crawl_command,
        stage="crawl",
        manifest_path=manifest_path,
        manifest=manifest,
    )
    if rc:
        print(
            "STOP: crawl failed. Rerun the identical command to resume."
        )
        return rc

    print(f"crawl pages: {json_count(pages)}")
    print(f"crawl report domains: {json_count(crawl_report)}")

    scoring_command = [
        sys.executable,
        ROOT / "lead_scoring.py",
        "--input",
        pages,
        "--output",
        scored,
        "--queue",
        queue,
    ]

    rc = run_command(
        scoring_command,
        stage="scoring",
        manifest_path=manifest_path,
        manifest=manifest,
    )
    if rc:
        print(
            "STOP: scoring failed. Crawl evidence remains preserved."
        )
        return rc

    print(f"scored organizations: {json_count(scored)}")

    if args.skip_enrichment:
        print()
        print("Enrichment skipped by request.")
        print(f"Batch workspace: {workspace}")
        return 0

    enrichment_command = [
        sys.executable,
        ROOT / "run_enrichment.py",
        "--pages",
        pages,
        "--results",
        scored,
        "--output",
        enriched,
        "--state",
        state,
        "--audit",
        audit,
        "--review",
        review,
    ]

    rc = run_command(
        enrichment_command,
        stage="enrichment",
        manifest_path=manifest_path,
        manifest=manifest,
    )
    if rc:
        print(
            "STOP: enrichment failed. Workspace is retained for rerun."
        )
        return rc

    manifest["updated_at"] = utc_now()
    manifest["counts"] = {
        "queue": json_count(queue),
        "pages": json_count(pages),
        "crawl_report_domains": json_count(crawl_report),
        "scored": json_count(scored),
        "enriched": json_count(enriched),
        "review": json_count(review),
    }
    atomic_json(manifest_path, manifest)

    print()
    print("===== BATCH COMPLETE THROUGH ENRICHMENT =====")
    print(f"queue:     {manifest['counts']['queue']}")
    print(f"pages:     {manifest['counts']['pages']}")
    print(f"scored:    {manifest['counts']['scored']}")
    print(f"enriched:  {manifest['counts']['enriched']}")
    print(f"review:    {manifest['counts']['review']}")
    print(f"workspace: {workspace}")
    print()
    print("No CRM synchronization or outreach was performed.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
