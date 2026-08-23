# Product Task List

Last reconciled: 2026-08-23

This file tracks current work. Historical v34/v35 recommendations are preserved
in the handoff and audit documents; they are not active tasks unless listed
below.

## Completed

- [x] Normalize manual CSV leads into a deduplicated crawl queue.
- [x] Import search, maps, association, directory, CSV, and JSON exports while
  retaining source provenance.
- [x] Add a live Alberta Funeral Service Association directory provider.
- [x] Crawl home, contact, about, team, staff, director, people, and location
  pages with same-domain controls and resumable batches.
- [x] Extract public phone numbers, email addresses, named decision-makers,
  business names, and postal addresses.
- [x] Extract schema.org data from supplied and embedded JSON-LD.
- [x] Calculate contact completeness and contact-quality scores.
- [x] Preserve structured contact intelligence through scoring and CRM records.
- [x] Create auditable email and phone validation evidence without claiming
  external deliverability or reachability checks.
- [x] Generate unresolved-domain research queues and apply reviewed domain
  replacements.
- [x] Separate platform candidates from client campaign leads.
- [x] Rank platform candidates and generate reviewable outreach drafts without
  sending email.
- [x] Validate the current implementation with the automated test suite.

## Next Milestone: Operator Interface

- [x] Define the smallest operator workflow and acceptance criteria:
  import leads, run or resume discovery, review failures, inspect ranked leads,
  approve outreach drafts, and update CRM action status. See
  `audit/OPERATOR_WORKFLOW.md`.
- [x] Choose the interface delivery model: a local Flask/Jinja web application.
  See `audit/OPERATOR_INTERFACE_DECISION.md`.
- [x] Add read-only views for queues, crawl progress, research failures, ranked
  results, contact evidence, and draft outreach.
- [x] Add guarded operator actions:
  - [x] Import preview and confirmation.
  - [x] Controlled crawl start and resume.
  - [x] Reviewed research-domain decisions.
  - [x] Unsent draft approval.
  - [x] CRM action creation, start, and completion.
- [x] Add an end-to-end test for the complete local operator workflow.

## Later Integrations

- [x] Add local email syntax, normalization, and DNS/MX validation with explicit
  `LOCAL_VALID` and `DNS_VALID` confidence states. DNS evidence must not claim
  that an individual mailbox exists.
- [x] Add local phone parsing, E.164 normalization, validity, region, and number
  type metadata with an explicit `METADATA_VALIDATED` state. Metadata must not
  claim carrier reachability.
- [x] Add an optional ZeroBounce mailbox-verification adapter. Keep
  `deliverability` as `NOT_CHECKED` when no external check has run.
  - [ ] Validate against a live account. Deferred optional enhancement: no API
    key or billing authority is available in the repository environment.
- [x] Add an optional Twilio Lookup v2 carrier/line-type/reachability adapter.
  Keep the existing unknown/not-checked states when no external check has run.
  - [ ] Validate against a live account. Deferred optional enhancement: no
    account credentials, paid Lookup authorization, or Canadian line-type
    approval is available.
- [x] Select EspoCRM as the initial external CRM target. Decision supplied on
  2026-08-22; retain the local CRM database as the auditable source of workflow
  state. See `audit/CRM_INTEGRATION_DECISION.md`.
- [x] Implement an idempotent EspoCRM REST adapter with explicit field mapping,
  bounded retries, safe secret handling, and locally audited sync outcomes.
- [x] Add deterministic fake-adapter tests for EspoCRM synchronization.
  - [x] Add a pinned, localhost-only EspoCRM Compose stack and a credential-safe
    live validation harness under `dev/espocrm`.
  - [x] Validate against a live self-hosted EspoCRM 10.0.5 instance using an
    Account-only API-key user. Two independent two-pass runs reused remote ID
    `6a8a9037cd3452fe3`; exactly one Account exists. Bad authentication and an
    unreachable endpoint failed closed without changing local lead state. See
    `audit/CRM_INTEGRATION_DECISION.md`.
- [x] Add a controlled CANA public member-directory provider beyond AFSA, with
  selectable Canada and United States coverage.
- [x] Expand live validation beyond Alberta and document Canada/USA coverage,
  duplicate handling, retrieval rates, and contact yield. See
  `audit/CANA_LIVE_DISCOVERY_VALIDATION.md`.

## Next Milestone: Evidence-Driven Enrichment Automation

Added 2026-08-23 after repository inspection found that crawled HTML, JSON-LD,
contact validation, and operator review exist, but enriched facts have no common
provenance contract and there is no persistent, bounded record-level agent
runner. This milestone extends the existing file-based pipeline rather than the
operator UI's deliberately in-process crawl-job mechanism.

- [x] Add deterministic organization and contact enrichment from already
  permitted crawl/discovery evidence. Every fact must retain its value, source
  URL/type, observation time, detector/version, confidence, verification state,
  direct/derived status, and stable deduplication key; conflicts must remain
  visible rather than being silently overwritten.
- [x] Add freshness and input-fingerprint caching so unchanged records are
  skipped, stale facts can be refreshed, and no external call is repeated merely
  because the runner restarts.
- [x] Add bounded, persistent enrichment and quality-control agents with explicit
  input/output contracts, retry/failure/skip audit records, safe interruption
  recovery, and idempotent output.
- [x] Add quality findings for provenance/confidence violations, contact-domain
  mismatches, unsupported decision-maker claims, duplicate entities/contacts,
  conflicting facts, and scores or CRM-readiness claims unsupported by evidence.
  Ambiguous findings must enter review rather than silently changing canonical
  data.
- [x] Surface enrichment facts, uncertainty, conflicts, evidence, freshness, and
  recommended research actions in the existing operator lead review.
- [x] Exercise the real local enrichment-agent workflow end to end with a
  representative multi-page record, including repeat-run skip/idempotency,
  interrupted-run recovery, malformed/conflicting inputs, and operator output.

Validation evidence: the real 35-organization local crawl produced 1,480 unique
facts in 22 fields with no missing mandatory provenance and 70 completed durable
agent tasks. A second identical run skipped all 70 tasks. Review output retained
13 canonical-name conflicts and 22 cross-domain email-attribution findings
across 19 organizations. An adversarial first pass incorrectly treated expected
multi-valued staff, location, social, and page-canonical facts as conflicts; the
resolution rule was narrowed to singleton identity fields and regression-tested.

## Current Milestone: Continuous Gap Remediation

Evidence and triage details are preserved in `audit/GAP_REGISTRY.md`.

- [x] **GAP-2026-010 (CRITICAL): prevent SSRF through imported crawl targets.**
  Ingestion currently accepts loopback, link-local metadata, and private IP URLs,
  and the crawler does not validate resolved address scope. Reject non-public
  hostnames/IP literals, validate public DNS addresses before requests and after
  redirects, prove unsafe targets receive zero requests, and retain public crawl
  behavior with deterministic resolver tests.
- [x] **GAP-2026-001 (HIGH): fail closed on blocked or failed agent dependencies.**
  Evidence: the orchestrator returns partially modified records after an agent
  exception and continues past retry-exhausted upstream work. Fix the orchestration
  layer so publication aborts, previous atomic outputs survive, dependent agents
  do not run, and bounded retry/recovery tests prove the behavior on disk.
- [x] **GAP-2026-002 (HIGH): separate observed schema names from canonical identity.**
  Evidence: 13/35 real records report false canonical conflicts from branch,
  staff-section, or legal-variant names, while `martinbros.com` is a genuine site
  identity mismatch. Preserve schema names as sourced candidates and add a
  deterministic mismatch finding that retains the true defect. Add entity/name
  fixtures and verify the real review delta without forced resolution.
- [x] **GAP-2026-003 (MEDIUM): make freshness transitions observable through the
  agent cache.** Add crawl observation timestamps, use them for page facts, and
  expire only quality-cache validity at fact horizons. Tests must prove stale
  detection after unchanged-input skips without repeatedly re-enriching old pages.
- [x] **GAP-2026-004 (MEDIUM): unify quality-based CRM/outreach readiness.** Six
  identity-conflicted records currently say `Ready For Outreach`. Add one
  fail-closed safety policy used by quality results, review artifacts, and the
  operator views, with regression tests for blocking and non-blocking findings.
- [x] **GAP-2026-005 (LOW): add reproducible coverage/gap metrics and regression
  comparison.** Generate machine-readable field/contact/quality/staleness/agent
  metrics from local artifacts, compare with a prior snapshot using explicit
  thresholds, test it deterministically, and document the command.
- [x] **GAP-2026-006 (LOW): implement the existing technology detector from
  observed HTML markers.** Add conservative, provenance-retaining enrichment for
  real WordPress/Elementor/Gravity Forms/FuneralTech/GTM patterns, with negative
  fixtures and a measured production-data result.
- [x] **GAP-2026-011 (MEDIUM): retain explicit public parent/operating
  relationships.** Beaverlodge and Oliver's first-party pages explicitly name
  Swan City Funeral Services Ltd., but parent coverage is 0/35. Extract only
  bounded legal phrases with page provenance; do not infer ownership from shared
  contacts. Add positive/negative fixtures and verify both real records.

Gap-cycle evidence: production enrichment increased from 1,480 to 1,610 facts:
119 positive technology signatures and 11 explicit first-party parent-company
observations, with no loss of organization or contact coverage. Review records
fell from 19 to 15; false canonical conflicts
fell from 13 to 0, while one genuine website-identity mismatch and all 22
contact-domain attribution findings remain visible. The repeat run skipped 70/70
tasks, metrics reported no regression, 34 Accounts are CRM-safe, and 20 records
are outreach-ready under the shared quality policy.

## Data and Release Hygiene

- [x] Align `verify_audit.py` with the production feature detector. Discovered
  during final pipeline validation: its duplicate keyword table reported signals
  that `lead_scoring.py` correctly left below threshold.
- [x] Make `verify_audit.py` usable when generated data is intentionally absent
  from version control by accepting and validating an explicit input path.
- [x] Make reviewed resolution multi-file persistence rollback-safe. Discovered
  during adversarial review: per-file atomic replacement did not protect the
  ledger, retry queue, summary, and remaining queue as one logical update.
- [x] Review the current uncommitted migration, especially intentionally removed
  historical data and the move to `data/seeds`, `data/private`,
  `data/generated`, and `legacy/reference_campaign`. Evidence is recorded in
  `audit/DATA_MIGRATION_REVIEW.md`.
- [x] Confirm generated or private records are excluded from version control.
- [x] Update stale v34 handoff language or clearly mark those documents as
  historical.
- [x] Commit the reconciled implementation as a tested checkpoint. Authorization
  was granted on 2026-08-22; complete after final validation.
- [x] Commit progressive local verification and EspoCRM integration as a
  separately validated checkpoint.
- [x] Commit the reproducible EspoCRM test stack and live validation harness as
  a statically validated checkpoint while retaining the host-runtime blocker.

## Current Verification

- Automated tests: 125 passing on 2026-08-23.
- Local enrichment validation: 35 organizations, 1,610 unique facts across 24
  fields, 15 explicit review records, and a 70-of-70 unchanged-task skip on the
  second run. No uncontrolled enrichment network requests were made.
- Controlled DNS validation: MX-positive and Null-MX/negative domain behavior
  confirmed without claiming mailbox deliverability.
- Live EspoCRM validation: authenticated Account create/update/read round trip,
  remote-ID reuse, local mapping/audit persistence, and failure isolation
  passed on 2026-08-23.
- Live AFSA validation: 35 scored companies from 52 normalized website domains.
- Platform-candidate dataset: 27 reviewed candidates, including 21 site-verified
  records and 6 evidence-only records.

See `README.md`, `audit/LIVE_DISCOVERY_VALIDATION.md`, and
`audit/PRODUCT_DIRECTION.md` for operating instructions and supporting evidence.
