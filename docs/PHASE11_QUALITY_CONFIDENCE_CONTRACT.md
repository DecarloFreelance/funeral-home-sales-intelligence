# Phase 11 Quality and Confidence Contract

## 1. Purpose

Phase 11 provides explainable, deterministic quality reports over evidence already
stored by the source, entity, website, page, people, and business-fact phases. A
score describes evidence quality and reporting readiness; it is not a canonical
truth decision and is never an approval or merge decision.

## 2. Scope and non-goals

Version 1 computes scores for `entity`, `website`, `website_page`, `person`,
`person_observation`, and `business_fact`. Source records are included as
provenance inputs but do not receive a standalone score until a source-quality
contract defines how source trust, retrieval, and payload completeness should be
combined.

This phase does not approve websites, select primaries, merge entities or
people, assign branches, resolve business-fact conflicts, alter reviews,
dispositions, remediation tasks, observations, or crawl/enrich any source.

## 3. Policy version and result shape

Every result carries `quality-confidence-v1`. The result contains the subject
type and ID, component scores, an overall score, a readiness label, stable
reason codes, stable warnings, and an input fingerprint. The fingerprint is a
SHA-256 of the canonical JSON of the computed input summary; timestamps and
reviewer state are excluded unless they are themselves an explicit input.

Scores are integers in `[0, 100]`. Component values may be `null` when a
dimension is not observable for that subject. The overall score is a weighted
mean of available components, rounded to two decimal places; unavailable
components are excluded from both numerator and denominator and are not treated
as negative evidence.

Readiness is deterministic: `insufficient_evidence` when no component is
available or there is no supporting evidence; `low` for 0–49.99, `medium` for
50–74.99, and `high` for 75–100.

## 4. Dimensions and formulas

The independent dimensions are:

- `source_quality`: quality of the linked source/page record when observable;
- `identity_confidence`: existing website/page identity evidence or accepted
  person-review evidence, never a newly inferred identity;
- `provenance_quality`: completeness of persisted source, page, website, and
  entity links plus URL, content hash, and evidence fields;
- `evidence_quality`: explicit evidence strength and extractor confidence;
- `consistency`: agreement among current observations in the relevant group;
- `completeness`: presence of applicable evidence fields, not business absence;
- `freshness`: age of the authoritative stored observation/check timestamp;
- `review_confidence`: existing human review state, where applicable.

Weights are policy constants, normalized over non-null components:

| subject | weighted components |
| --- | --- |
| entity | identity 25, evidence 30, provenance 25, completeness 20 |
| website | identity 35, evidence 25, provenance 20, freshness 20 |
| website_page | identity 35, evidence 20, provenance 25, freshness 20 |
| person | evidence 25, provenance 30, consistency 15, review 20, freshness 10 |
| person_observation | evidence 35, provenance 30, identity 15, review 20 |
| business_fact | evidence 30, provenance 30, consistency 20, completeness 10, freshness 10 |

`business_fact` evidence begins with the stored observation confidence, gives
full credit only for complete persisted provenance, and gives corroboration
credit only for distinct page/content-hash snapshots. Repeated rows from the
same page and content hash are not independent. Page identity observability is
an identity input, not website approval. Ambiguous scope is a completeness and
warning issue, never a branch assignment.

For people, only active canonical people and active affiliations/contacts are
current by default. Accepted observation reviews are positive review evidence;
rejected/deferred history remains visible but does not become accepted evidence.
Merged people are excluded unless historical mode is explicitly requested.

For websites and pages, stored confidence, status, identity score,
`identity_observable`, checks, and evidence are reported as evidence. Status
values such as `selected` do not get converted into an approval score.

## 5. Missing, conflict, and historical semantics

Missing data produces a null component and a reason such as
`missing_provenance`, `no_observation`, or `not_observable`; it is not a false
fact. Incompatible normalized values lower `consistency` and produce a
`conflict` warning, but every value remains reportable and no winner is chosen.
Repeated identical observations are reported as repetition, not independent
corroboration. Historical snapshots are retained and can be included by an
explicit flag; they do not contaminate current scores. A changed content hash
is a new observation under the Phase 10 lifecycle.

For business facts, current mode uses the latest stored content-hash snapshot
per page. Conflict checks and corroboration counts use that current population;
`--include-historical` deliberately expands them to all retained snapshots.
Thus a superseded value remains auditable without making a current conflict by
itself. Current person evidence counts only observations with an accepted Phase
9 review; rejected or deferred observations remain historical warnings and are
not positive evidence.

Freshness uses the explicitly supplied UTC reference time and the most recent
authoritative persisted timestamp. Age buckets are: 0–30 days = 100, 31–180 =
75, 181–365 = 50, 366–730 = 25, and older than 730 = 0. No timestamp means
`null`, not stale.

## 6. Provenance contract

Reports retain the IDs that support each result: source record where available,
entity, website, page, observation/fact ID, source URL, content hash, extractor
version, and evidence/review references. Existing normalized relationships are
used rather than copying mutable canonical identity fields into a new table.
The input fingerprint makes the exact computed input set reproducible without
persisting a second mutable score table.

## 7. Storage and extraction boundary

No Phase 11 migration is required. Scores are computed in read-only service
queries from migrations 1–17. No snapshots are persisted: the current database
already preserves historical observations and their hashes, and the explicit
reference time plus policy version provides reproducibility. Phase 10's offline
body-to-observation seam remains the only extraction boundary; Phase 11 never
accepts or stores HTML and performs no network I/O.

## 8. Reporting and query strategy

`quality score --subject-type TYPE --subject-id ID` returns one structured
result. `quality summary` returns deterministically sorted results and supports
subject type, entity, readiness, score bounds, conflict-only, incomplete-only,
and historical filters. `quality export --output DIRECTORY` writes
`quality_scores.csv`, `quality_components.csv`, and `quality_warnings.csv` with
stable columns and row ordering.

The service uses bounded grouped queries: one query for the requested subject
population and batched joins/aggregates for observations, checks, reviews, and
facts. It does not query once per score row.

## 9. Required tests and safety invariants

Fixture-only tests cover no evidence, complete and incomplete provenance,
identity evidence, repetition versus duplicate snapshots, conflicts, ambiguous
scope, freshness with an injected reference time, people and website evidence,
deterministic JSON/CSV, invalid IDs, migration reapplication, and before/after
read-only snapshots of entity, website, review, people, disposition, and
remediation state.

Quality reporting cannot mutate any table, create decisions, infer branch scope,
resolve identity, crawl public sites, or write the production database.

## 10. Deferred work

Standalone source confidence, persisted score snapshots, source-quality
calibration, aggregate BI dashboards, automatic threshold actions, canonical
business-fact projections, and refresh/change tracking remain deferred. Any
future score-policy or taxonomy change must use a new explicit policy version;
historic rows must not be reinterpreted silently.
