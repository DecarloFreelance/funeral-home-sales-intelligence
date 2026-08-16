# Canada Funeral Intelligence — Phase Status

This document records the implementation status of the phase plan in
[`PROJECT_PLAN.md`](PROJECT_PLAN.md). Status is based on the current source
tree, migrations, tests, CLI, and documented execution paths. A phase marked
complete means its current repository scope is implemented and validated; it
does not mean that national data coverage or every future enhancement is
complete.

## Current baseline

- Migrations: `0001` through `0023`
- Test baseline: 516 passing tests at the time this status was recorded
- Validation tools: `compileall`, `pytest`, `ruff check`, and `ruff format`
- Database: SQLite with foreign-key enforcement and deterministic migrations
- Extraction boundary: crawling persists page metadata; People and
  Business-Fact extraction remain explicit operator actions
- Fetch state: page-level network observability is recorded in `website_pages`
  by migration `0023`; no cache or freshness-based request suppression exists

## Phase matrix

| Phase | Area | Status | Evidence / scope note |
|---:|---|---|---|
| 0 | Foundation | Complete | Configuration, logging, SQLite connections, transaction helpers, migration engine, package CLI, baseline tests, and migrations `0001`–`0005`. |
| 1 | Source Registry | Complete | Source registry models, validation, seeding, and `sources list/show/validate`; registry metadata is stored separately from collection. |
| 2 | Import Framework | Complete | CSV/JSON/XML/HTML-table import paths, provenance, raw source payloads, checksums, import history, row errors, and idempotent import behavior. |
| 3 | Normalization | Complete | Scalar, business-name, address, people, and URL normalization with normalized-value provenance and dataset-scoped execution. |
| 4 | Entity Resolution | Complete | Deterministic matching, fuzzy candidates, review decisions, evidence, canonical materialization, merge history, and rollback paths. Identity decisions remain operator-controlled. |
| 5 | Website Discovery | Complete | Candidate discovery, source evidence, confidence, shared-domain handling, branch-page handling, website review, manual intake, and discovery runs. |
| 6 | Website Verification | Complete | DNS/TLS/HTTP probing, bounded redirects, content checks, identity observability, website checks, and bounded batch verification with separate retry state. |
| 7 | Page Discovery | Complete | Bounded priority-driven same-site crawling, page classification, redirect-proven host aliases, safe same-run URL aliases, page persistence, and crawl tests. |
| 8 | Staff Intelligence | Complete | Explicit `website extract-people`, persisted person observations, current-probe authority over stale metadata, provenance, and manual review workflow. |
| 9 | Contact Intelligence | Complete | Contact/person analysis and persistence paths exist within the extraction and people workflows; public contact evidence remains provenance-backed. |
| 10 | Business Intelligence | Complete | Taxonomy, extraction, storage, reporting, and explicit post-crawl `business-facts extract`; generic `other` pages remain bounded by supported patterns. |
| 11 | Quality and Confidence | Complete | Quality scoring, reporting, evidence/freshness inputs, and CLI/reporting surfaces are implemented. |
| 12 | Reporting and Exports | Complete | CSV/JSON/SQLite snapshot exports, coverage and quality reports, and read-only reporting paths. |
| 13 | Refresh and Change Tracking | Complete | Offline refresh runs, semantic fingerprints, change records, historical observations, and explicit refresh reporting. Network retrieval is not coupled to refresh. |
| 14 | Additional Verticals | Complete — framework scope | Reusable vertical registry, membership storage, and CLI plumbing are implemented. Additional sector-specific data collectors and detectors remain follow-up work. |

## Completed cross-cutting infrastructure

- Website candidate evidence and discovery-run persistence (`0021`–`0022`)
- Offline pipeline orchestration (`0020`)
- Provincial/source integrations for Alberta, Manitoba, Ontario, and Nova
  Scotia, plus manual/source-registry intake paths
- Canonical People operator backlog and runbook
- Page-level fetch-state observability (`0023`) with deterministic content
  hashes and independent file-backed state persistence
- Redirect/canonical same-run alias handling without durable canonical-alias
  storage

## Operational boundaries

The following are intentional boundaries, not missing automatic wiring:

- Website crawling does not automatically run People extraction.
- Website crawling does not automatically run Business-Fact extraction.
- The offline pipeline does not run either website extraction stage.
- People review population, decisions, and canonical resolution are explicit
  operator actions.
- Page fetch state currently records network truth but does not suppress
  future requests.
- Website-level verification and batch retry state remain separate from
  page-level fetch state.

## Coverage status

Implementation completeness should not be confused with Canadian market
coverage. The current development database is a source-derived working
inventory, not a national census. Coverage expansion remains a data-acquisition
task: add authoritative provincial and territorial sources, import them through
the existing provenance-preserving framework, resolve duplicates, and measure
location and website coverage by jurisdiction.

## Recommended next work

1. Add the next authoritative provincial or territorial source through the
   existing source registry and import framework.
2. Re-run normalization and entity-resolution review for the new dataset.
3. Generate and review website candidates from the new source evidence.
4. Verify approved website candidates in bounded batches.
5. Run explicit page, People, and Business-Fact extraction for approved sites.
6. Track coverage, unresolved matches, website reachability, and freshness by
   province and source.

## Validation record

The latest implementation validation associated with this status document
reported:

```text
python -m compileall -q src tests     PASS
python -m pytest -q                   516 passed
python -m ruff check src tests        PASS
python -m ruff format --check src tests PASS
git diff --check                     PASS
```

Re-run the validation commands after subsequent changes.
