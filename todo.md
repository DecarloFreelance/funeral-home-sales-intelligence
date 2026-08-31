# Product Task List

Last reconciled: 2026-08-24

## Directory 955 precision enrichment (2026-08-31)

- [x] **GAP-2026-044 (HIGH): fetch and attribute the 45-record P4 known-domain
  cohort.** Evidence: all 45 V9-unresolved records have one verified domain but
  no matching cached crawler page, so offline extraction cannot proceed. Impact:
  a bounded first-party crawl can recover contact/location evidence without
  spending search quota, but shared domains and redirects require existing
  crawler safety and branch-level attribution. Responsible subsystem: isolated
  scale crawler plus offline contact attribution. Acceptance: prepare a
  deterministic source, crawl with workers=8, timeout=15, max-pages=12 and
  restartable checkpoints, use no LangSearch, classify every target, merge only
  branch-safe contacts from exact V9, retain provenance/review/shared evidence,
  conserve 955 unique records, keep staff/DM metrics fixed, run adversarial and
  full tests, and preserve CRM SHA-256. **VALIDATED:** the deterministic source
  reduced 45 locations to 32 domain crawl identities; the bounded run made 274
  path attempts and retained 12 pages from 5 domains while 27 domains failed
  closed. Five explicit branch phones were merged for Melita, Portage la
  Prairie, Carberry, Neepawa, and Minnedosa. Four cross-domain redirects,
  Willmor's unmapped Glenboro/Holland phones, Wolkowski's wrong Kamsack branch,
  and labeled faxes remained blocked. V10 has 269 resolved plus 686 unresolved
  records, unchanged staff/DM metrics, byte-identical attribution reruns, 268
  tests plus 2 subtests passing, no LangSearch use, and unchanged CRM SHA-256.

- [x] **GAP-2026-043 (MEDIUM): fail-closed audit the three P3 cached-search
  businesses.** Evidence: cached results for Fletcher/Radville are generic
  Dignity pages, George/Wiarton resolves only to the different A. Millard George
  business in London, and Hendren/Lakefield resolves only to legacy obituary or
  service pages. Impact: accepting these results would create false website or
  branch-contact attribution. Responsible subsystem: cached-search recovery.
  Acceptance: conserve and classify all cached results offline, explicitly block
  wrong-business, obituary, and generic corporate evidence, retain all three as
  unresolved, make no canonical merge, and preserve CRM SHA-256. **VALIDATED:**
  all 13 cached results were conserved and classified; the London George result,
  four Hendren memorial pages, and eight generic Dignity results remained
  blocked. No value was merged, 268 tests plus 2 subtests pass, and the CRM hash
  remains canonical.

- [x] **GAP-2026-042 (HIGH): bulk-audit the remaining P1 cached-fetch cohort.**
  Evidence: offline inspection of the 10 review and 54 weak-only P1 businesses
  found nine first-party pages with phones explicitly paired to target branch
  names or addresses, alongside labeled faxes, shared emails, and ambiguous
  Cropo/Cardinal/Everest multi-location rows. Impact: trustworthy cached branch
  contacts remain outside the canonical dataset, while naive domain extraction
  would smear contacts. Responsible subsystem: offline P1 branch attribution
  and canonical materialization. Acceptance: classify all 64 businesses, merge
  only explicit branch-block phones from exact V8, retain shared/review evidence,
  reject fax and cross-branch values, preserve provenance, regenerate unresolved
  records, keep staff/DM metrics fixed, conserve 955 unique records, prove
  deterministic output, run the full suite, and preserve CRM SHA-256.
  **VALIDATED:** all 64 remaining P1 businesses were classified offline; nine
  explicit branch phones were merged for Shediac, Brockville, Chelmsford,
  Hanmer, Dashwood, Exeter, Lucan, Seaforth, and Spiritwood. Barclay's
  two-column HTML structure was checked directly, not inferred from flattened
  proximity. Four shared-email groups, labeled faxes, and ambiguous
  Cropo/Cardinal/Everest mappings remained unmerged. V9 has 264 resolved plus
  691 unresolved records, unchanged staff/DM metrics, byte-identical repeat
  output, 268 tests plus 2 subtests passing, and unchanged canonical CRM hash.

- [x] **GAP-2026-041 (HIGH): recover branch-safe contacts from the P2 cached
  crawler cohort.** Evidence: the ten-record P2 queue contains a first-party
  Interlake contact page with a Selkirk address, phone, labeled fax, and email;
  its About page explicitly identifies owner Rick Kotaska, while other P2 pages
  include shared MacKenzie contacts and generic Dignity pages. Impact: one
  unresolved record has locally cached trustworthy contacts, but naive
  domain-wide extraction would smear shared or corporate contacts. Responsible
  subsystem: offline crawler-evidence attribution and canonical materialization.
  Acceptance: audit all ten records offline, join Kotaska identity to the
  Selkirk contact block, reject the fax, leave shared/generic contacts unmerged,
  preserve provenance, materialize exact V7 to V8, retain 955 unique records and
  unchanged staff/DM metrics, regenerate unresolved records, and preserve CRM.
  **VALIDATED:** all ten P2 records were classified offline; CFI-0514 gained
  `info@interlakecremation.ca` and `+12044821040` from its explicit Selkirk
  block with separate Kotaska identity evidence. The labeled fax, shared
  Stonewall/Teulon values, generic Dignity contact, and unproductive cached
  pages remained unmerged. V8 has 255 resolved plus 700 unresolved records,
  unchanged staff/DM metrics, byte-identical repeat output, 268 tests plus 2
  subtests passing, and unchanged canonical CRM SHA-256.

- [x] **GAP-2026-040 (HIGH): resolve Falconer Clinton contact scope before V7.**
  Evidence: cached first-party contact-page text pairs `+15194829521` directly
  with the Clinton Chapel block, but repeats `info@falconerfuneralhomes.com` in
  both Clinton and Goderich blocks; V3's distance classifier proposed both as
  branch-safe. Impact: merging the email would smear organization-shared data
  onto one branch. Responsible subsystem: offline branch attribution and
  canonical 955 materialization. Acceptance: audit the cached body and its hash,
  classify the Clinton phone separately from the shared email and labeled fax
  values, preserve provenance, merge only audit-approved values from exact V6,
  retain 955 unique records and unchanged staff/DM counts, regenerate the
  unresolved queue, prove an adversarial Goderich-contact exclusion, and leave
  CRM SHA-256 unchanged. **VALIDATED:** the cached body SHA-256 matched the V3
  evidence; its two repeated renderings each pair `+15194829521` with Clinton,
  `+15195241221` with Goderich, and the same email with both branches. V7 merged
  only the Clinton phone, preserved the email as organization-shared, rejected
  both labeled faxes, and produced 254 resolved plus 701 unresolved records.
  All 955 IDs remain unique; staff/DM metrics are unchanged; a repeat run was
  byte-identical; 268 tests plus 2 subtests pass; and the CRM retained SHA-256
  `c06bee94b72a8bbde83e1755a9897800543f038e255e6e2db72cca744a736b9e`.

## Autonomous national discovery (2026-08-26)

- [x] **GAP-2026-039 (HIGH): add a bounded, evidence-preserving national
  discovery lifecycle.** Evidence: the production-representative scale artifact
  contains 211 domain-grouped organizations and 255 location observations, but
  repository inspection finds only manually invoked AFSA/CANA acquisition and
  file import; there is no persistent query ledger, canonical discovery
  candidate record, deterministic search-gap planner, first-party publication
  policy, novelty saturation measure, or resumable discovery coordinator.
  This prevents safe incremental national expansion and would require an
  operator to reconstruct provenance and retry state between runs. Implement at
  the discovery subsystem, reusing URL/network safety, the priority crawler,
  association providers, atomic persistence, and organization/location
  semantics. Acceptance: bounded plan/run/status commands; idempotent candidates
  and query spending; checkpoint/retry/quota behavior; fail-closed verification,
  publication, and quarantine; machine/human reports; dry-run/protected-state
  invariance; adversarial tests including the Foster userinfo regression; and a
  documented unattended invocation. No outreach, CRM, pilot, or raw-source
  writes are permitted. General web search remains unavailable until an
  authorized provider adapter and credentials are configured. **VALIDATED:**
  the deterministic planner prioritizes the three uncovered territories and
  suppresses fresh completed queries; a one-query/three-result fixture run
  produced one high-confidence publication, one evidence-rich parent/redirect
  quarantine, and one generic-directory rejection. The full suite passes 264
  tests plus 2 subtests. Raw AFSA/CANA inputs, the 211-domain scale queue and
  enriched results, the broader discovered-page artifact, and the 40-event
  pilot history retained their pre-run SHA-256 values. No general search API or
  credential is configured, so live general-web discovery remains an explicit
  limitation rather than fabricated validation.

## Discovery website identity safety (2026-08-26)

- [x] **GAP-2026-038 (HIGH): reject userinfo-bearing organization website
  values before canonical domain creation.** Evidence: the AFSA source value
  `http://info@fostercmgarvey.com` is parsed by `urlsplit` with
  `info` as userinfo and `fostercmgarvey.com` as the hostname, after which
  `normalize_website` silently emits `http://fostercmgarvey.com/` and
  `build_crawl_queue` creates an unsupported standalone identity. Fix website
  normalization to fail closed on URL userinfo, retain the rejected source value
  and association provenance on the in-memory lead with a bounded quality flag,
  and prove valid URLs, email separation, multi-location retention, unrelated
  records, and deterministic generation remain intact. Do not rewrite AFSA raw
  data or merge locations by brand name. **VALIDATED:** the generated queue fell
  from 52 to 51 identities by removing only the unsupported
  `fostercmgarvey.com` entry; the valid `fostermcgarvey.com` St. Albert record
  remains; 244 tests plus 2 subtests pass; and AFSA raw source and the 34-event
  pilot history remained byte-identical.

## Online pre-arrangement pathway detection (2026-08-24)

- [x] **GAP-2026-037 (HIGH): recognize explicit verb-first online
  pre-arrangement pathway labels.** Evidence: Beaverlodge's current retained
  first-party navigation repeatedly contains `Pre-Arrange Online`, but
  `public_business_enrichment` 1.5.1 recognizes only noun-first
  `online/virtual arrangements`, leaving `digital.online_arrangements` absent
  after enrichment. Extend the positive detector and bounded-scan safety mirror
  only to explicit online-arrangement/form language; retain provenance,
  freshness, organization isolation, and negative bounded-scan semantics.
  A supported Beaverlodge append refresh additionally proved that legacy pages
  without `discovery.queue_domain` were not superseded because the replacement
  key did not fall back to the page URL hostname, duplicating the refreshed
  organization while leaving unrelated organizations intact.
  Acceptance: positive label variants produce current first-party facts,
  adjacent offline/online wording remains negative, Beaverlodge refreshes via
  the normal crawl/enrichment/package commands, and pilot event bytes do not
  change. **VALIDATED:** a single-organization live crawl retained four current
  first-party pages and the same-domain pre-arrangement form link; enrichment
  1.5.2 produced four corroborated positive facts for both pre-planning and
  online arrangements; the regenerated non-sendable package uses
  `PREARRANGEMENT_PATHWAY_REVIEW`; 242 tests plus 2 subtests pass; and the
  28-event pilot history remained byte-identical at SHA-256
  `ea0a59323a0780a1f50760c1ecb5a6f115b6b7d4c67c58a70c5898f0c06fbf45`.

## Pre-planning information pathway coverage (2026-08-24)

- [x] **GAP-2026-028 (HIGH): retain a bounded commercial angle for positive
  first-party pre-planning evidence without online-arrangements evidence.**
  Evidence: `build_first_prospect_package` has one all-or-nothing gate requiring
  `digital.online_arrangements`, so current McCaw and Beaverlodge pre-planning
  facts cannot produce a package. Require current organization-bound website
  and positive pre-planning facts, preserve the stronger online-arrangements
  angle, and prove lifecycle/read-only invariants with deterministic tests.
  Validated with 240 tests and 2 subtests; real McCaw and Beaverlodge package
  generation preserved the 27-event pilot history byte-for-byte at SHA-256
  `edd4c9048ae10c198b563bcd9ba59ba9acc2f4a5b3a791c6369b5399b0bbb289`.

This file tracks current work. Historical v34/v35 recommendations are preserved
in the handoff and audit documents; they are not active tasks unless listed
below.

## Selected-angle revision safety (2026-08-24)

- [x] **GAP-2026-026 (HIGH): supersede materially outdated customer-facing
  angle copy without rewriting selected-angle history.** Evidence: Gregory's
  immutable v1 selection retained unresolved sender placeholders after the
  package generator was hardened. Require an explicit same-organization,
  same-observation, same-improvement, same-evidence supersession chain; resolve
  the current angle deterministically; reject missing, foreign, or stale
  evidence; and keep draft preparation and implementation feasibility bound to
  the current revision. Validated with append-only, idempotency, adversarial,
  downstream-consumer, and named pilot regression tests.

## Duplicate-contact safety (2026-08-24)

- [x] **GAP-2026-027 (CRITICAL): prevent prior-contact prospects from being
  presented or prepared as fresh initial outreach.** Evidence: Gregory was
  manually emailed while its projected state still appeared eligible, then
  received a duplicate message before external-send event
  `e259499faca544f70e7d1364` was reconciled. Centralize append-only contact
  history assessment across stats, selection, and draft preparation; fail
  closed on ambiguous lifecycle evidence; add a read-only ranked `next-unsent`
  command; and prove real pilot history and event bytes remain unchanged.
  Validated with transition, reconciliation, progressed-state, ranking,
  malformed-history, preparation-guard, idempotency, and read-only tests. The
  real command excluded all five contacted cohort members and preserved the
  27-event file byte-for-byte at SHA-256
  `edd4c9048ae10c198b563bcd9ba59ba9acc2f4a5b3a791c6369b5399b0bbb289`.

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

## Production-Representative Scale Validation

- [x] **GAP-2026-013 (HIGH): checkpoint controlled crawls per organization.**
  A deliberate interruption after completed live requests proved the CLI wrote
  nothing until the whole queue finished. Persist pages and reports atomically
  after every domain, add explicit resume filtering, duration/outcome metrics,
  and prove restart skips completed work.
- [x] **GAP-2026-014 (HIGH): retain and fail closed organizations with no usable
  website evidence.** The scorer previously emitted only domains represented by
  fetched pages, dropping 159/211 canonical organizations at scale. Accept the
  normalized queue, preserve directory facts, assign no missing-feature or
  opportunity claims, mark research required, and block CRM/outreach.
- [x] **GAP-2026-015 (HIGH): block ambiguous multi-location domains from CRM.**
  Domain deduplication can represent several named branches while the canonical
  label names only one. Require explicit network-versus-branch review before CRM
  synchronization; test the readiness boundary.
- [x] **GAP-2026-016 (MEDIUM): distinguish directory contact candidates from
  role-verified people.** Preserve the 160/211 public association contacts as
  sourced candidates without increasing named-person or decision-maker coverage,
  and label both categories clearly for operators.
- [x] **GAP-2026-017 (MEDIUM): resolve deterministic email-attribution noise.**
  Reject the observed hosted-form placeholder `filler@godaddy.com`; retain
  first-party-published cross-domain addresses with a low-severity confirmation,
  while directory-only/free/corporate mismatches remain reviewable.
- [x] **GAP-2026-018 (LOW): extend scale observability.** Metrics now distinguish
  direct/derived coverage and track crawl outcomes/duration, provenance omissions,
  duplicate fact IDs, readiness rates, agent retry counts, and task duration.
- [x] **GAP-2026-021 (LOW): remove repeated full audit-file parsing.** The
  211-record repeat run reparsed the growing JSON audit for every one of 422
  events. Load the validated list once per locked run while retaining atomic
  event persistence and the existing format; batch only unchanged skip events
  under the pipeline lock. A production repeat completes in 2.4 seconds.
- [x] **GAP-2026-022 (HIGH): preserve complementary multi-source location
  fields.** Duplicate location rows replaced earlier rows wholesale, allowing a
  later empty email/phone to erase existing evidence and misattribute fields to
  one generic source URL. Merge nonempty fields and retain field-level source
  URLs; exercise them through queue ingestion and contact extraction tests.

Scale evidence: 342 AFSA/CANA records containing 257 websites normalized to 211
domains across all ten provinces, a reduction of 46 duplicate website records.
The controlled crawl reused 31 domains and attempted 180; 22 new domains yielded
45 pages and 158 remained in the research queue. All 211 organizations were
scored/enriched into 3,257 facts across 25 fields. The repeat pass skipped
422/422 tasks. Zero provenance omissions, duplicate fact IDs, stale facts, agent
 failures, or metric regressions were observed. See `audit/SCALE_VALIDATION.md`.

## Ambiguity resolution (2026-08-24)

- [x] **GAP-2026-023 (HIGH): recover exact parent-network location pages without
  collapsing branch identity.** Require directly observed legacy-domain redirect
  plus strong name/location evidence; retain provenance and original entity ID;
  leave weak candidates unresolved.
- [x] **GAP-2026-024 (HIGH): isolate shared parent URLs and location-scope crawl
  evidence.** Persist by organization plus URL, replace successful per-entity
  recrawls atomically, and exclude generic parent contact/about pages.
- [x] **GAP-2026-025 (MEDIUM): give every quality finding an explicit durable
  research question.** Include review-only entities, preserve refusal reasons,
  expose them to operators, and measure outcomes and idempotency.

Production evidence: 172 candidates produced 245 explicit questions; 116 were
safely resolved (115 exact location pages and one existing first-party email
confirmation), while 129 remain unresolved. Review-required fell 172→99;
`NO_USABLE_WEBSITE_EVIDENCE` fell 159→44; CRM-safe rose 45→122 and
outreach-ready 39→112. All 115 location pages were fetched under their original
entity identity. A 15-record sample across the eight provinces represented by
automatic resolutions matched fetched page title/location evidence. No merge,
parent/branch reassignment, CRM bulk sync, or outreach occurred.

## Manual ambiguity review (2026-08-24)

- [x] **GAP-2026-026 (HIGH): add an auditable finding-level manual-review
  workflow.** Generate stable review IDs from source findings; retain research
  questions, evidence, location, and related-entity context; append rather than
  overwrite decisions; preserve conflicting history; require evidence for
  resolving dispositions; derive eligibility without mutating canonical data.

Scale evidence: the same 99 review-required organizations produce 131 stable
finding-level items (47 duplicate, 44 no-website, 21 email, nine multi-location,
eight shared-address, and two website-identity). A repeated refresh is
byte-identical. Before operator decisions, 131 remain unresolved, 102 block CRM,
and all 131 block outreach. No generated decision, entity merge, page/contact
movement, or readiness change was fabricated during validation.

## Agent health and commercial readiness (2026-08-24)

- [x] **GAP-2026-027 (CRITICAL): enforce current quality approval at every CRM
  and action boundary.** Architecture tracing found that the reachable legacy
  `outreach_export.py` command could write all scored records to SQLite without
  reading `quality_control`, while SQLite and `espocrm_sync.py` had no durable
  readiness gate. Persist explicit fail-closed `crm_sync_safe` and
  `outreach_ready` flags; filter exports; reject unsafe individual/bulk Espo
  sync; prevent an existing unsafe action from starting; migrate missing flags
  to false; add transactional and missing-state regressions. **VALIDATED:** the
  targeted CRM/agent contract suite passes, absent state is rejected, and the
  211-record production metrics remain unchanged. See
  `audit/AGENT_HEALTH_COMMERCIAL_READINESS.md`.

Audit conclusion: all canonical record agents are active and their durable
outputs are consumed. The evidence-backed internal presentation produced 25
safe shortlist records and five audit prototypes without CRM writes or outreach.
Legacy revenue/opportunity prose remains explicitly internal-only; replacing it
is not required for the controlled pilot path and is not an active task.

## Manually controlled first revenue pilot (2026-08-24)

- [x] **GAP-2026-032 (MEDIUM): add bounded implementation-feasibility advice for
  selected commercial angles.** Reuse `COMMERCIAL_ANGLE_SELECTED`, current
  organization/evidence fingerprints, retained first-party pages, form facts,
  positive technology/provider markers, and the durable agent orchestrator.
  Classify provider/direct/unknown access, bounded scope, discovery questions,
  verification, and re-scope triggers without changing identity, readiness,
  pilot state, CRM, outreach, pricing, or customer systems. **VALIDATED:** real
  dry runs flag Mission View and Foothills for provider confirmation and retain
  Fernhill as unknown-access; repeated unchanged work skips idempotently. See
  `audit/IMPLEMENTATION_FEASIBILITY.md`.

- [x] **GAP-2026-028 (HIGH): bridge verified intelligence to an auditable human
  revenue experiment.** The commercial package could rank prospects but had no
  customer-safe content schema, guarded approval-before-draft lifecycle,
  append-only pilot history, manual offer assignment, or outcome/revenue funnel.
  Add a deterministic ten-record cohort, same-organization evidence checks,
  structurally safe wording, non-sendable previews, explicit state transitions,
  three manually priced offer variants, descriptive pilot metrics, CLI/tests,
  stale-evidence approval rechecks, and a runbook. **VALIDATED:** ten artifacts
  generate idempotently; all remain
  `CANDIDATE`; zero approvals, drafts, contacts, CRM writes, network requests, or
  sends were fabricated. See `audit/FIRST_REVENUE_PILOT.md`.

- [x] **GAP-2026-029 (HIGH): prevent unsupported first-contact claims and require
  pre-send publication review.** Foothills' retained first-party homepage links
  a `Pre-Arrangements Form`, but the commercial shortlist treated online
  arrangements as a bounded non-detection; approval also treated current
  readiness and fact freshness as sufficient without an auditable human review
  of publication, business relevance, no-CEM language, sender identification,
  and unsubscribe readiness. Detect contrary retained page evidence before
  producing non-detections; add organization-bound append-only pre-send review,
  stale-evidence approval checks, an internal first-prospect package, CLI/tests,
  and operator guidance. **VALIDATED:** Foothills' unsupported negative is
  removed, its package remains `REVIEW_REQUIRED`, and no approval, contact, CRM
  write, or send was recorded. See `audit/FIRST_REVENUE_PILOT.md`.

- [x] **GAP-2026-030 (MEDIUM): represent public form schemas without speculative
  conclusions.** Foothills' first-party intake form exposed commercially useful
  requirement and field-schema observations that the retained enrichment model
  could not represent, while form length or sensitive-looking labels must not
  become automatic defects. Add a non-submitting, organization-bound, versioned
  form analyzer; neutral semantics and requirement states; privacy-context
  observations; human-review-only candidates; CLI, dataset metrics, append-only
  human pilot annotation, regression tests, and documentation. **VALIDATED:**
  the retained 211-record run produces deterministic form intelligence without
  changing facts, identity, quality, CRM/outreach readiness, approval, contact,
  CRM, or outreach state. See `audit/FORM_INTELLIGENCE.md`.

- [x] **GAP-2026-031 (HIGH): bind guarded drafts to the explicitly selected
  evidence-specific angle.** Fernhill's confirmed form-label observation and
  customer-safe preview existed only in an ignored evaluation package, while
  `pilot draft` still consumed the older cohort preview. Add an append-only
  angle-selection event, current evidence/identity fingerprints, operator
  inspection, approval/preparation revalidation, and fail-closed no-fallback
  behavior. **VALIDATED:** Fernhill's canonical selection is
  `PREVIEW_ONLY_NOT_PREPARED`; its three organization-bound evidence references
  resolve; zero approval, contact, send, CRM, or form-submit action occurred.

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

- [x] **GAP-2026-036 (HIGH): render pathway-review previews without unresolved
  sender placeholders.** Evidence: the Gregory package's selected-angle preview
  exposed literal sender placeholders even though validated pilot conventions
  already identify Alex De Carlo and Digital Pathway; the presend checklist
  separately retains mandatory sender-identification gating. Render that
  established identity in preview copy, use owner names only from current
  organization-owned person evidence, make no defect or outcome claim, and
  preserve the non-sendable preview and approval/presend boundaries.
  **VALIDATED:** Gregory's generated preview uses the established Alex De Carlo
  / Digital Pathway convention without fabricating missing contact details;
  owner names require current first-party owner evidence, the sender-identification
  presend check still fails closed, and 222 tests plus 2 subtests pass.

- [x] **GAP-2026-035 (HIGH): generate organization-bound pathway-review angles
  from current first-party evidence.** Evidence: the nominally generic first
  prospect-package constructor hard-codes Foothills identity/copy and requires a
  Foothills-specific `Pre-Arrangements Form` page label. Gregory's current
  enrichment instead contains resolvable first-party preplanning and online-
  arrangements facts, while its form-intelligence inventory has no record.
  Generalize package identity/copy and produce a cautious
  `PREARRANGEMENT_PATHWAY_REVIEW` interpretation from those facts without
  asserting any defect. Preserve same-organization selection, evidence and
  identity fingerprints, stale/missing-evidence failure, and all lifecycle/send
  controls; prove Gregory generation and Mission View/Foothills regressions.
  **VALIDATED:** the supported CLI package command generated Gregory's
  organization-bound review angle from two current corroborated enrichment
  facts while retaining an empty Gregory form inventory; 221 tests and 2
  subtests pass, and no angle-selection or lifecycle event was recorded.

- [x] **GAP-2026-034 (HIGH): derive effective prepared-draft presentation from
  pilot history.** Evidence: live `pilot show` reports Cornerstone as
  `CONTACT_PREPARED` while retaining the cohort's blocked generic preview,
  despite its canonical transition event containing the selected-angle
  `PREPARED_UNSENT` draft. Overlay only a real persisted prepared draft in the
  effective read model; preserve blocked previews before preparation and after
  external-send reconciliation without local drafting. **VALIDATED:** the live
  Cornerstone read model now exposes its persisted selected-angle prepared
  draft, while focused and full workflow tests retain fail-closed boundaries.

- [x] **GAP-2026-033 (HIGH): include reconciled external sends in pilot
  lifecycle aggregation.** Evidence: the live per-prospect reducer reports the
  externally reconciled Foothills send as `CONTACTED`, while aggregate stats
  report two contacted prospects and retain one current `MANUAL_REVIEW` state.
  Make stats share the canonical lifecycle-event interpretation, count only the
  reached `CONTACTED` state for reconciliation, preserve approval/draft reach,
  and prove subsequent replies, funnel denominators, normal transitions, and
  duplicate rejection remain correct. **VALIDATED:** live stats now report 3
  contacted prospects with current states of 3 `CONTACTED` and 7 `CANDIDATE`;
  approval and draft reach remain 2, and the focused and full suites pass.

- Automated tests: 222 passing plus 2 subtests on 2026-08-24.
- Production-scale validation: 211 organizations and 4,648 enrichment facts;
  form intelligence separately inventories 1,898 page-level forms across 152
  organizations without changing the 122 CRM-safe or 112 outreach-ready records.
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
