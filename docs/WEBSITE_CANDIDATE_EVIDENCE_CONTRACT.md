# Website Candidate Evidence Contract

Version: `website-candidate-evidence-v1`

## Purpose

This contract defines how offline source evidence produces reviewable website
candidates. It strengthens candidate inspection and ranking without making a
website ownership, branch, approval, or primary-site decision.

The workflow remains offline. Reachability is measured only by the separately
authorized verification workflow and is never candidate evidence.

## Available source signals

The source model has two relevant layers:

- `source_records.source_url` is the provenance URL of the source record. It is
  not itself an organization website signal.
- `normalized_values` may contain source-derived `url`, `domain`, or `email`
  values. A normalized `url` is an explicit website signal; a normalized
  `domain` is an explicit source-domain signal; an email domain is an inferred
  signal only.

The current production data contains email signals from the Manitoba regulator
dataset and no normalized URL/domain signals. The contract nevertheless
supports explicit signals when future source imports provide them.

## Evidence taxonomy

Evidence classes are ordered by ownership relevance:

1. `explicit_source_website` — a source record explicitly identifies the value
   as the business website. This requires source-field semantics to be known;
   an arbitrary source URL is not sufficient.
2. `explicit_source_url` — a normalized source `url` value when the importer
   cannot distinguish a website-specific field from a general URL field.
3. `source_domain` — a normalized source `domain` value explicitly present in
   source data.
4. `normalized_url` — a normalized URL representation retained for evidence
   and deduplication. It is subordinate to the source-field classification.
5. `normalized_domain` — a normalized domain representation retained for
   evidence and deduplication.
6. `email_domain` — a domain derived from a normalized email address. It never
   establishes website ownership or branch membership.
7. `manual` — reviewer-supplied evidence, reserved for existing manual paths.

`source_url` remains an existing storage compatibility value for source-record
provenance. It is not treated as an explicit website URL unless a future source
contract explicitly says so.

## Candidate generation and evidence

Candidate generation, evidence strength, reachability, entity association,
branch association, review status, and primary assignment are separate facts:

- generation creates a normalized `(entity_id, normalized_url)` candidate;
- evidence explains why it was generated;
- reachability comes only from a verification check;
- entity and branch association remain source/review questions;
- review status remains pending until a reviewer acts;
- `is_primary` remains false unless existing manual selection semantics set it.

One candidate may have multiple evidence rows. Evidence rows retain source
record and normalized-value identifiers where available. Evidence is append-only
for audit purposes and duplicate logical evidence is idempotent.

## Generic email domains

Version 1 suppresses candidate generation from these consumer domains:

`gmail.com`, `outlook.com`, `hotmail.com`, `icloud.com`, `proton.me`,
`protonmail.com`, and any domain whose normalized value ends with `.yahoo.com`
or `.yahoo.ca`.

The suppression policy is deterministic and versioned as
`generic-email-domain-v1`. Suppressed source values remain in
`normalized_values`; they simply do not produce website candidates.

## Normalization and equivalence

URL normalization is case-insensitive for scheme and host, removes fragments,
removes a trailing host dot, removes a leading `www.` for domain comparison,
preserves meaningful paths and queries, and supplies HTTPS for bare domains.
Equivalent `(entity_id, normalized_url)` values are one candidate. Domains are
lowercase and have no trailing dot or leading `www.`.

Malformed values are ignored safely and remain available in their original
source/normalized rows. No DNS or HTTP request is made during normalization.

## Strength and ranking

The strongest evidence class is selected by this exact order:

`explicit_source_website` (700), `explicit_source_url` (600),
`source_domain` (500), `normalized_url` (400), `normalized_domain` (300),
`manual` (200), `email_domain` (100).

These numbers are rank weights, not ownership probabilities. A candidate's
support count is the number of distinct logical evidence signals, deduplicated
by `(source_record_id, normalized_value_id, evidence_class, normalized_value)`.
Evidence from the same source record is not independent merely because it has
multiple rows.

Candidate ordering is:

1. strongest evidence weight descending;
2. distinct supporting-source count descending;
3. explicit path evidence before root-only evidence;
4. non-shared candidates before shared candidates;
5. normalized URL ascending;
6. entity ID ascending;
7. website ID ascending.

The ranking affects presentation and bounded candidate selection only. It does
not alter confidence, review status, website kind, or primary assignment.

## Shared domains and branches

The same normalized domain may belong to multiple entity candidates. Shared
status is derived from distinct entity IDs and remains review-required. A
branch-specific URL path is evidence of a path signal, not automatic proof of
branch ownership. A root corporate domain never establishes branch membership.

Evidence from unrelated entities is not merged into a candidate's support
count. No organization hierarchy is inferred.

## Storage extension

Migration `0022_add_website_candidate_evidence_metadata.sql` adds nullable
`normalized_value_id`, `evidence_class`, `derivation_method`,
`derivation_version`, and `raw_value` columns to `website_evidence`. Existing
rows are backfilled conservatively from their existing `evidence_type`; their
historical meaning is not reinterpreted. A uniqueness index makes repeated
logical evidence idempotent while retaining distinct source provenance.

## Reporting surface

The existing `website list` surface exposes deterministic candidate evidence
summary fields: strongest evidence class and weight, supporting evidence count,
evidence classes, source dataset IDs, source record IDs, normalized-value IDs,
shared-domain status, review-required status, discovery method, and derivation
version. JSON uses stable key and list ordering. Existing candidate population
remains the write surface; listing is read-only.

## Safety invariants

This feature never performs DNS/HTTP, never persists HTML, never approves or
rejects a website, never assigns a primary website, never changes entities or
branch hierarchy, and never changes people, facts, quality, or refresh state.

## Explicitly deferred

- live verification and crawling;
- source acquisition or web search;
- automated website ownership or branch decisions;
- organization hierarchy inference;
- source-specific website-field semantics not present in the repository;
- a large consumer-domain blacklist;
- canonical website selection.
