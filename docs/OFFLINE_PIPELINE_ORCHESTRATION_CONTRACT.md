# Offline Pipeline Orchestration Contract

## 1. Purpose

`offline-pipeline-v1` coordinates the existing local source import, normalization,
entity matching, review-queue preparation, and baseline entity materialization
functions. It provides durable execution state, deterministic summaries, and
safe stage-boundary resume behavior.

This is an operational layer. It does not add identity policy.

## 2. Run identity and inputs

Each non-dry run has a row in `pipeline_runs`. A run is identified by its row ID
and records:

- pipeline version (`offline-pipeline-v1`)
- source dataset ID and input path/format
- SHA-256 input fingerprint
- external-ID field, requested terminal stage, and fuzzy-match flag
- creation/start/completion timestamps
- optional predecessor run ID
- lifecycle status and bounded error summary

The input fingerprint is SHA-256 over a deterministic JSON object containing the
pipeline version, source dataset, input file bytes, input format, external-ID
field, terminal stage, and fuzzy flag. Timestamps are excluded.

The same input may be run more than once. A matching fingerprint explains
equivalent input; it does not suppress execution because existing idempotent
domain functions remain authoritative.

## 3. Supported stages and ordering

Version 1 supports these stages in fixed order:

1. `import`
2. `normalize`
3. `deterministic_match`
4. `fuzzy_match` (optional)
5. `review_queue`
6. `materialize`

The import stage requires a local CSV or JSON file and a registered source
dataset. Later stages operate on the selected dataset where the existing API
supports a dataset filter; matching, review preparation, and materialization
use their established repository-wide semantics.

The runner never invokes collectors, probes, crawlers, page extraction, people,
business-fact, quality, reporting, refresh, or vertical mutation paths.

## 4. Lifecycle

Run statuses are `pending`, `running`, `completed`, `failed`, and `cancelled`.
Stage statuses are `pending`, `running`, `completed`, `failed`, and `skipped`.
Each stage has one current row and an attempt counter. Stage counters are
normalized columns; bounded error rows retain stage, message, and optional
record context.

A run becomes `completed` only after every selected stage completes. A failure
marks the run `failed`; later stages remain pending. Cancellation is explicit
metadata and is not inferred from process interruption.

## 5. Resume and retry

Resume is allowed only for a `failed` or `cancelled` run. A completed run cannot
be resumed. Resume uses the original input fingerprint and configuration and
starts at the first non-completed stage. Completed stages are not repeated.

The runner claims the run by a transactional status precondition. A second
resume observing `running` fails, preventing concurrent execution. A failed
stage may be retried by resume; its attempt count increments and its prior
failure remains queryable. A changed input/configuration cannot resume the old
run.

Stage functions commit their own domain transaction, then the runner commits
the stage result. A stage failure is recorded without marking later stages
complete. Existing domain transactions provide rollback for the failing stage.

## 6. Dry run

Dry runs are entirely non-persistent. The runner parses the local input and
reports projected import counts and the selected stage plan, but does not create
a pipeline row or call mutating domain functions. Projected later-stage counts
are explicitly marked unavailable rather than fabricated.

## 7. Idempotence and provenance

The runner delegates idempotence to existing implementations:

- import checksum/external-ID detection
- normalized-value identity
- match candidate and evidence uniqueness
- review-queue uniqueness
- entity-source membership checks

It does not add shadow deduplication. Source records retain their existing
import-run provenance; pipeline stages retain the pipeline run ID and counters.

## 8. Manual-review and mutation boundaries

The runner may create review candidates and pending review rows. It never
approves, rejects, defers, merges, or rolls back identities. Materialization is
the existing baseline operation that creates one branch entity for an
unmaterialized source record; it does not merge records or infer organization
hierarchy.

No website, person, business-fact, quality, refresh, vertical, or review
decision state is changed beyond preparation of the existing entity review
queue.

## 9. Failure semantics

Row-level import parse errors remain import-run errors and do not by themselves
fail the pipeline. Stage exceptions are fatal to that run and are recorded in
`pipeline_run_errors`. Counters distinguish input, processed, inserted,
unchanged, skipped, review, and error outcomes where the underlying operation
provides them; unavailable counters are zero rather than inferred.

## 10. CLI and deterministic output

The CLI provides:

- `pipeline run`
- `pipeline resume --run-id ID`
- `pipeline show --run-id ID`
- `pipeline list`
- `pipeline stages --run-id ID`

Run and resume accept local input/source options, `--through-stage`,
`--skip-fuzzy`, and `--dry-run` where applicable. JSON uses sorted keys and
stable stage ordering. List/show commands do not mutate domain state.

## 11. Concurrency and safety

Only one execution may own a run at a time. SQLite transactions and a status
precondition protect run claims. No distributed worker model is introduced.
The pipeline command never performs network I/O and must be run against a
development or temporary database; production remains read-only and is never
migrated by this feature.

## 12. Deferred work

Deferred are public-source acquisition, website/page orchestration, background
workers, scheduling, parallel execution, automatic review decisions, automatic
merges, and pipeline-specific orchestration of people/business-fact extraction.
