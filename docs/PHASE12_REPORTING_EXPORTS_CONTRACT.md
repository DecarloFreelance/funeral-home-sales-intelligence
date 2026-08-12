# Phase 12 Reporting and Exports Contract

## 1. Purpose and boundaries

Phase 12 provides reproducible operational and analytical reports over the
durable evidence already stored by Phases 0–11. Reports are projections only.
They never approve websites, select primaries, merge entities or people,
resolve facts or anomalies, complete remediation, change reviews, crawl, or
write production data.

The structured report contract is `reporting-v1`. JSON uses stable field names,
CSV uses fixed headers, null values are emitted as empty CSV cells, arrays are
sorted and serialized with `|`, and rows are sorted by their documented IDs or
stable keys. Reports accept an explicit UTC reference time; the CLI defaults it
only at the outer boundary and includes it in every report.

## 2. Current and historical state

Current reports are the default:

- entities: `status = active`; merged and inactive entities are historical;
- websites: candidates through selected sites, excluding rejected sites;
- pages: pages belonging to current-report websites;
- people: `status = active`; merged/inactive people are historical;
- person evidence: accepted review evidence is current positive evidence;
  rejected, deferred, and pending rows remain reportable workflow history;
- dispositions: non-stale current fingerprints; stale rows are historical;
- remediation: open, in-progress, blocked, completed, and cancelled tasks for
  current anomalies; stale tasks are historical;
- business facts: latest content-hash snapshot per page, with all values in
  that snapshot retained so conflicts remain visible;
- quality: Phase 11 `quality-confidence-v1` current scores.

`--include-historical` includes inactive/merged people and entities, rejected
websites, all business-fact snapshots, and stale workflow rows where the report
supports them. Historical inclusion never changes the meaning of current
counts; it adds separately labelled historical rows/counts.

## 3. Coverage denominators

Coverage metrics always expose `numerator`, `denominator`, `percentage`, and a
definition ID. The denominator is the eligible current population after the
metric's stated exclusions. Unknown or not-applicable rows are excluded from
the denominator and counted in `excluded` when useful. A zero denominator
produces `percentage: null`, never zero.

Version-1 coverage definitions:

| ID | numerator | denominator |
| --- | --- | --- |
| `entities_with_source` | active entities linked to a source record | active entities |
| `entities_with_website` | active entities with a non-rejected website | active entities |
| `entities_with_page` | active entities with a page on a non-rejected website | active entities |
| `entities_with_people_observation` | active entities with a linked person observation | active entities |
| `entities_with_canonical_person` | active entities with an active person affiliation | active entities |
| `entities_with_business_fact` | active entities with a current business fact snapshot | active entities |
| `entities_with_quality` | active entities with at least one quality component | active entities |
| `people_with_email` | active people with an active normalized email | active people |
| `people_with_phone` | active people with an active normalized phone | active people |
| `people_with_accepted_evidence` | active people with accepted observation evidence | active people |

Organization and branch counts are descriptive partitions of active entities,
not percentages of one another. Shared websites do not assign branch facts or
people to a branch; only explicit entity relationships count.

## 4. Report surfaces

The minimal CLI is:

- `report coverage`: coverage metrics and active organization/branch counts;
- `report quality`: readiness distribution, score averages, component coverage,
  conflict and incomplete counts;
- `report business`: current fact-key coverage, state counts, scope counts, and
  entity coverage;
- `report people`: active people, accepted/rejected/deferred review counts,
  contact coverage, anomaly counts, and remediation state counts;
- `report summary`: all four report sections in one deterministic JSON object;
- `report export --output DIRECTORY`: the sections as JSON files, CSV files,
  and `report_manifest.json`.

Existing domain exports remain unchanged; this export is additive.

## 5. Manifest and snapshots

The export manifest records `report_version`, reference time, migration version,
filters, generated filenames, row counts, and SHA-256 hashes. File order and
manifest key order are deterministic. No random snapshot ID is generated.

Phase 12 does not persist snapshots. A live report plus an explicit reference
time and manifest hash is sufficient for current consumers, and the repository
has no approved retention or restore semantics for report snapshots. SQLite
snapshot persistence is deferred to a future contract; export commands never
write the application database.

## 6. Query and privacy rules

Reports use grouped SQL and existing domain services where practical. They do
not load raw HTML, infer branches from shared domains, or duplicate the Phase
11 scoring formulas. Evidence snippets are not included in aggregate reports.
Only intentionally stored fields and IDs are exported.

## 7. Required tests and invariants

Fixture-only tests cover empty and partial databases, denominator correctness,
historical isolation/inclusion, branch separation, business-fact conflicts,
quality policy reuse, people workflow counts, fixed reference time,
deterministic JSON/CSV/manifest hashes, duplicate-safe joins, and read-only
before/after state checks. Reports do not mutate any durable domain table and
make no network requests.

## 8. Deferred work

SQLite snapshots, missing/dead-site specialist reports, source contribution
analysis, duplicate-review dashboards, refresh/change reports, and broader
operational dashboards remain deferred until their own retention, denominator,
or lifecycle semantics are defined.
