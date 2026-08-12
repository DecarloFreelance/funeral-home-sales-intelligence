# Phase 13 Refresh and Change Tracking Contract

## 1. Purpose and boundaries

Phase 13 records how supported offline refresh observations differ between
completed runs. It preserves prior evidence and reports deltas; it does not
declare canonical truth.

It supports `website_page`, `person_observation`, and `business_fact`
observations. Source imports, entity identity, website approval, canonical
people, dispositions, remediation, and quality scores retain their existing
lifecycles and are not forced into this comparison model.

There is no crawler or network acquisition in this phase. Callers provide
already-observed metadata through an offline service.

## 2. Refresh runs

Each run has an ID, `run_type`, `scope_type`, optional scope value, UTC
reference time, status, extractor/config fingerprint, lifecycle timestamps,
and optional error text. Valid statuses are `running`, `completed`, `failed`,
and `cancelled`. Only a completed run is a comparison baseline. A run is
explicitly complete only when the caller invokes completion; a failed run is
never authoritative.

One run may contain many observed items. Items are keyed by
`refresh_run_id + subject_type + subject_key`; retries are idempotent when the
key and fingerprint are identical and reject conflicting duplicate input.

## 3. Current and historical selection

Refresh history does not replace domain current-selection rules. Website pages
and person observations remain append-only source observations; business facts
use Phase 10's latest page content-hash snapshot for current reporting.
Canonical people use their active/merged state, dispositions use stale state,
and remediation uses its explicit task status. A completed refresh is only the
latest comparison baseline for the same run type and exact scope. Failed or
cancelled runs are historical metadata and cannot become baselines.

## 4. Logical keys and fingerprints

The fingerprint policy is `refresh-change-v1`. Fingerprints are SHA-256 over
canonical sorted JSON with volatile timestamps excluded.

| subject | logical key | semantic fingerprint fields |
| --- | --- | --- |
| website_page | website ID + normalized URL | website ID, normalized URL, page kind, content hash, status code, content type |
| person_observation | page ID + normalized name + role + email + phone | page ID, normalized identity/contact fields, branch context |
| business_fact | page ID + fact key + scope + scope entity + normalized value | page ID, fact key, value kind, normalized value, scope, scope entity, content hash |

Raw database rows and timestamps are never hashed. Ordering of multi-values is
normalized before hashing. Page content hashes are retained as evidence of a
snapshot change; raw HTML is never stored.

## 5. Change events

Meaningful events are `added`, `changed`, `missing`, and `reappeared`. Unchanged
items do not create events. A changed fingerprint with the same logical key is
`changed`; a newly observed logical key is `added`; a previously absent item
returning is `reappeared`.

When a complete run omits an item present in the immediately previous completed
run, one `missing` event is recorded and the run item is marked absent. This is
not deletion, closure, or negation. A later presence produces `reappeared`.
No automatic removal event is emitted because source completeness is not
established by this phase.

Business-fact absence does not negate an old fact. Staff-page absence does not
deactivate a person. Website/page disappearance does not close a business.

## 6. Staleness and scope

Staleness remains domain-specific and is not automatically materialized by a
refresh event. Existing quality/reporting reference-time rules remain the
authoritative freshness semantics. Scope equality includes exact run type,
scope type, and scope value, preventing shared-domain or cross-entity event
contamination.

## 7. Storage and immutability

Migration 0018 adds `refresh_runs`, `refresh_run_items`, and `change_events`.
Run items preserve the observed logical key, fingerprint, reference ID, and
presence for every completed comparison. Events retain previous/current
fingerprints and references, reason codes, and deterministic metadata JSON.
Change-event rows and completed run identity fields are protected by SQLite
triggers against update/delete. Event insertion is transactional with run
completion.

## 8. CLI and reporting

Offline lifecycle commands are explicit: `refresh begin`, `refresh record`,
`refresh complete`, and `refresh fail`. Read-only commands are `refresh runs`,
`refresh show`, and `refresh changes`. JSON output is sorted and deterministic;
changes are ordered by run, subject type, subject key, and event ID.

Phase 12 reports are unchanged. Future reporting may consume change events by
using the same reference-time and versioning conventions.

## 9. Safety and required tests

Refresh operations never update entities, websites, pages, people, reviews,
facts, dispositions, remediation, or source rows. Tests use temporary SQLite
databases and fixture metadata only. They cover lifecycle validation,
fingerprint determinism, added/changed/unchanged/missing/reappeared behavior,
failed-baseline exclusion, duplicate retries, historical integrity, immutable
events, deterministic CLI output, migration idempotence, and production
read-only safety.

## 10. Deferred work

Scheduled jobs, background workers, authentication, alerts, automatic closure
or deactivation, source-import comparison, website verification comparison,
raw HTML archives, automatic staleness mutation, and broad event sourcing are
deferred.
