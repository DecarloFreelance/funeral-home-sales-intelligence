# Product Task List

Last reconciled: 2026-08-22

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

- Automated tests: 98 passing on 2026-08-22.
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
