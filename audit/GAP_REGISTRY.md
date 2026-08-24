# Gap Registry

This registry records evidence examined by the continuous gap-discovery loop.
`todo.md` remains the actionable work queue; this file preserves triage evidence
and rejected suspicions so they are not repeatedly rediscovered.

## GAP-2026-001 — Partial agent output can be published after failure

- Discovered: 2026-08-23
- Category: orchestration / data integrity
- Severity: HIGH
- Subsystem: `automation/orchestrator.py`, `run_enrichment.py`
- Evidence: `AgentOrchestrator.process` catches an agent exception, persists a
  failed task, then returns the partially modified record. A retry-exhausted
  upstream task uses `continue`, allowing dependent agents and final publication.
- Affected examples: any enrichment record when quality control fails; controlled
  `AlwaysFails` fixture in `tests/test_agent_orchestration.py`.
- Expected: failed or blocked dependencies abort publication and preserve the
  prior atomic output.
- Observed: partial output is eligible for publication and a dependent agent can
  run without its prerequisite.
- Root cause: failure state is persisted but not propagated to the pipeline.
- Confidence: HIGH
- Actionability: ACTIONABLE
- Acceptance: classified exception propagates; no output/review replacement;
  dependent agents do not run; retry limit remains bounded; regression test.
- Status: VALIDATED — classified failures now propagate, dependency execution
  stops, and atomic prior outputs survive; covered by orchestration tests.

## GAP-2026-002 — Schema branch names are treated as canonical identity

- Discovered: 2026-08-23
- Category: entity resolution / confidence
- Severity: HIGH
- Subsystem: `enrichment/company.py`, `enrichment/quality.py`
- Evidence: 13/35 records have canonical-name conflicts. Examples include Arbor
  Memorial and Dignity pages listing distinct branches, Serenity staff-section
  names, and harmless legal-suffix variants. `martinbros.com` is different: the
  AFSA name is Martin Bros. Funeral Chapels while the fetched site identifies
  Martin Bros. Distributing Co. Inc.
- Expected: schema names remain observed business/trading/branch candidates;
  canonical identity is not overwritten; a separate evidence-based mismatch
  finding retains the real `martinbros.com` defect.
- Observed: every Organization/LocalBusiness `name` becomes a singleton canonical
  name and creates broad false conflicts.
- Root cause: source semantics were collapsed during JSON-LD field mapping.
- Confidence: HIGH
- Actionability: ACTIONABLE
- Acceptance: false canonical conflicts disappear; deterministic material name
  mismatch remains review-blocking; branch/trading values and provenance remain;
  real-data comparison and regression fixtures pass.
- Status: VALIDATED — schema names remain sourced business-name candidates;
  real-data canonical conflicts fell 13 to 0 while `martinbros.com` remains a
  high-severity, CRM-blocking website-identity mismatch.

## GAP-2026-003 — Quality cache cannot notice facts becoming stale

- Discovered: 2026-08-23
- Category: freshness / orchestration
- Severity: MEDIUM
- Subsystem: crawler timestamps, `QualityControlAgent`, agent cache
- Evidence: quality fingerprints include fact content but not freshness state.
  An unchanged completed task is skipped forever, so crossing `stale_after` does
  not produce `STALE_ENRICHMENT`. Crawled pages also lack a fetch observation
  timestamp; enrichment time is currently substituted for source observation.
- Expected: future crawls retain observation time; quality cache validity expires
  at the earliest fact horizon and emits bounded refresh work without relabeling
  an old crawl as newly observed.
- Observed: stale transition is invisible unless another input changes.
- Root cause: cache validity has no time-dependent contract and crawl records omit
  fetch time.
- Confidence: HIGH
- Actionability: ACTIONABLE
- Acceptance: crawler timestamps are retained; page facts use them; a simulated
  horizon crossing reruns quality only and emits a stale finding; enrichment does
  not repeatedly rerun against unchanged old pages.
- Status: VALIDATED — crawls now timestamp observations and quality fingerprints
  transition once at stale horizons without rerunning unchanged enrichment.

## GAP-2026-004 — Record readiness can contradict blocking quality findings

- Discovered: 2026-08-23
- Category: quality control / operator correctness
- Severity: MEDIUM
- Subsystem: quality output and operator lead views
- Evidence: six records with identity conflicts show `Ready For Outreach` in
  scored data. Only the separate review artifact calculates CRM safety.
- Expected: quality output carries explicit CRM/outreach safety and reasons;
  operator lists/details do not present unresolved identity as ready.
- Observed: technically available conflict evidence and readiness labels disagree.
- Root cause: safety derivation exists only in the post-processing review queue.
- Confidence: HIGH
- Actionability: ACTIONABLE
- Acceptance: one shared policy drives quality output, review queue, and operator
  display; blocking identity/provenance findings fail closed; tests cover it.
- Status: VALIDATED — a shared fail-closed policy now supplies CRM/outreach safety
  and blocker reasons to records, review artifacts, and operator views.

## GAP-2026-005 — No reproducible gap/coverage metrics snapshot

- Discovered: 2026-08-23
- Category: observability / regression detection
- Severity: LOW
- Subsystem: enrichment operations
- Evidence: the 35-record coverage metrics in this audit required an ad-hoc
  script. There is no machine-readable command or previous-snapshot comparison.
- Expected: deterministic metrics cover field/contact/conflict/review/stale/agent
  outcomes and flag material regressions without treating coverage as correctness.
- Observed: operators cannot reproduce or compare the validated 1,480-fact
  baseline from a repository command.
- Root cause: the first enrichment milestone produced runtime artifacts but no
  metrics generator.
- Confidence: HIGH
- Actionability: ACTIONABLE
- Acceptance: bounded local command, JSON snapshot, prior-snapshot comparison,
  deterministic tests, documented invocation, and real-data baseline.
- Status: VALIDATED — `generate_gap_metrics.py` produces current/deduplicated
  history snapshots and thresholded regression findings; real baseline captured.

## GAP-2026-006 — Existing technology detector is an empty implementation

- Discovered: 2026-08-23
- Category: extraction / sales intelligence
- Severity: LOW
- Subsystem: `technology_detector.py`, enrichment
- Evidence: `detect_technology` always returns `{}` while fetched pages visibly
  contain WordPress, Elementor, Gravity Forms, FuneralTech, Google Tag Manager,
  and related public stack markers. Technology coverage is 0/35.
- Expected: conservative positive detection for stack markers already present in
  fetched HTML, with page provenance; absence must not imply a weakness.
- Observed: useful public indicators are discarded.
- Root cause: placeholder detector was never implemented or integrated.
- Confidence: HIGH
- Actionability: ACTIONABLE
- Acceptance: evidence-backed markers from real fixtures become enrichment facts;
  malformed/ambiguous text does not create unsupported signals; real-data impact
  is measured.
- Status: VALIDATED — conservative signatures produced 119 facts across 31/35
  organizations without interpreting absence as a negative signal.

## GAP-2026-010 — Imported crawl targets can reach local/private services

- Discovered: 2026-08-23
- Category: security / SSRF
- Severity: CRITICAL
- Subsystem: discovery ingestion and controlled crawler
- Evidence: `normalize_website("http://127.0.0.1:8080")`, RFC1918 targets, and
  `169.254.169.254` all produce accepted queue URLs. The crawler requests them
  without an address-scope check.
- Affected examples: any imported/manual source controlled by untrusted content;
  cloud metadata, loopback, and LAN services reachable from the host.
- Expected: non-public hostnames, IP literals, and domains resolving to any
  non-global address fail closed before a request; redirect targets are checked
  again; public targets continue to work.
- Observed: URL syntax and same-domain rules do not enforce network scope.
- Root cause: crawl URL canonicalization is not a network authorization boundary.
- Confidence: HIGH
- Actionability: ACTIONABLE
- Acceptance: static ingestion rejection, resolved-address enforcement before
  request and after redirects, no request for unsafe targets, deterministic
  resolver fixtures, and existing public crawl behavior unchanged.
- Status: VALIDATED — ingestion rejects non-public/literal targets and the crawler
  validates resolved addresses before requests; redirects are followed manually
  only after validating each destination, and unsafe test targets receive no
  request.

## GAP-2026-011 — Explicit public parent/operating relationships are discarded

- Discovered: 2026-08-23 (fresh post-remediation pass)
- Category: entity resolution / extraction
- Severity: MEDIUM
- Subsystem: organization enrichment
- Evidence: Beaverlodge's first-party staff page says it is “A Division of Swan
  City Funeral Services Ltd.”; Oliver's first-party footer says “Swan City Funeral
  Service LTD. operating as Oliver’s Funeral Home & Crematorium.” Both currently
  have no `organization.parent_organization` fact. The same pages independently
  support their two shared staff names.
- Expected: explicit division/operating-as legal phrases create sourced parent
  facts; shared contacts alone never infer ownership.
- Observed: parent relationship coverage is 0/35 despite direct page evidence.
- Root cause: enrichment consumes schema parent relationships but not the legal
  relationship phrases present in fetched page text.
- Confidence: HIGH
- Actionability: ACTIONABLE
- Acceptance: both real records identify Swan City with page provenance;
  unrelated prose and shared-person records do not create parent facts; repeat
  enrichment remains idempotent.
- Status: VALIDATED — bounded first-party legal phrases now produce sourced
  parent facts for Beaverlodge, Oliver's, and Dignity Memorial; a negative
  shared-staff fixture proves that co-occurrence alone creates no relationship.

## Triaged suspicions not promoted to tasks

### GAP-2026-007 — Cross-domain email findings are false positives

- Category: contact attribution
- Evidence: 22 findings include corporate domains, ISP/free mailboxes, aliases,
  and possible misspellings. The repository cannot deterministically prove their
  branch/person attribution from domain alone.
- Confidence that this is a defect: LOW
- Status: NOT_A_DEFECT
- Reason: the finding asks for review and does not reject the address or claim it
  is wrong. Suppression would hide genuine attribution risk.

### GAP-2026-008 — Shared staff imply incorrect attribution

- Category: contact attribution / ownership
- Evidence: Chris Clements and Brooke Skaley appear on both Beaverlodge and
  Oliver's public staff pages. Both pages explicitly associate with Swan City
  Funeral Services Ltd.
- Confidence that this is a defect: LOW
- Status: NOT_A_DEFECT
- Reason: two independent first-party pages directly support both associations.
  The shared ownership relationship is useful future evidence, but the contacts
  are not falsely attributed.

### GAP-2026-009 — Low careers/founding/livestream coverage is extractor failure

- Category: data coverage
- Evidence: coverage is respectively 3/35, 2/35, and 2/35. A review of present
  pages did not establish a systematic visible pattern missed by the extractors.
- Confidence that this is a defect: LOW
- Status: NOT_A_DEFECT
- Reason: absence of public evidence is not an implementation gap. Re-evaluate
  only when a concrete missed page/source pattern is captured.

### GAP-2026-012 — Empty legacy revenue/exporter stubs are active pipeline gaps

- Category: architecture / test coverage
- Evidence: `revenue.py` and `exporter.py` contain empty placeholder functions,
  but repository-wide reference search finds no imports or callers; maintained
  scoring, enrichment, metrics, and export workflows use other modules and
  commands.
- Confidence that this is a defect: LOW
- Status: NOT_A_DEFECT
- Reason: unreachable historical placeholders do not affect a documented or
  observed workflow. Implementing them would invent a parallel interface rather
  than remediate repository behavior.

## Scale-validation gaps (2026-08-23)

### GAP-2026-013 — Interrupted CLI crawl loses completed domains

- Category: recovery / observability
- Severity: HIGH
- Evidence: interrupting the 180-domain live crawl after eight domains left no
  new pages or per-domain report because persistence occurred only after the
  complete queue returned.
- Root cause: the CLI buffered the crawler's whole result list in memory.
- Acceptance: atomic per-domain page/report checkpoints; explicit resume skips
  terminal domains; duration/outcome metrics; live stop/restart and regression test.
- Status: VALIDATED — 56 live domains survived a second deliberate interruption;
  resume selected exactly the remaining 124 and duplicated no completed work.

### GAP-2026-014 — Zero-page organizations disappear or receive false opportunity claims

- Category: pipeline/scoring correctness
- Severity: HIGH
- Evidence: only 52/211 canonical domains had reusable pages. `lead_scoring.py`
  previously created organizations only while iterating pages, so 159 valid
  directory organizations would disappear; treating an empty page set as nine
  missing website features would also manufacture opportunity.
- Root cause: scoring had no normalized-queue input contract.
- Acceptance: retain all queue entities and directory provenance; use zero scores
  and no absence claims; mark research required; block CRM/outreach; test it.
- Status: VALIDATED — all 211 records are represented; all 159 zero-page records
  have zero opportunity/executive score and are fail-closed.

### GAP-2026-015 — Multi-location domain can sync one arbitrary branch identity

- Category: entity resolution / CRM correctness
- Severity: HIGH
- Evidence: `dignitymemorial.com` represents eight named locations in this
  cohort while the profile's canonical label is the first branch; eight other
  domains also contain multiple distinct location names.
- Root cause: domain deduplication correctly preserves locations, but Account
  readiness did not require a network-versus-branch mapping decision.
- Acceptance: material multi-location domains remain intact but CRM/outreach is
  blocked pending explicit identity review; single-location records unchanged.
- Status: VALIDATED — nine affected domains emit a deterministic review finding
  and are excluded from CRM-safe scale sampling.

### GAP-2026-016 — Public directory people are invisible to enrichment/operators

- Category: contact coverage / operator correctness
- Severity: MEDIUM
- Evidence: CANA exposes public contact candidates for 160/211 domains, retained
  by contact extraction but absent from enrichment facts and the operator view.
- Root cause: only website role-verified people entered the evidence layer.
- Acceptance: retain directory candidates with source and `DISCOVERED` state;
  never classify them as role-verified people or decision makers; expose labels.
- Status: VALIDATED — candidate coverage is 160/211 while role-verified named and
  derived decision-maker coverage correctly remain 11/211.

### GAP-2026-017 — Scale email attribution includes deterministic noise

- Category: contact attribution
- Severity: MEDIUM
- Evidence: `aquamations.ca` contained the hosted-form placeholder
  `filler@godaddy.com`; several other cross-domain addresses were directly
  published on the organization's own fetched page.
- Root cause: cleaning accepted a known template placeholder and quality ignored
  source type when assessing domain mismatch.
- Acceptance: reject only the observed placeholder; classify first-party page
  publication separately without suppressing directory/free/corporate ambiguity.
- Status: VALIDATED — placeholder count fell to zero; one current cross-domain
  address is first-party-confirmed; 21 unresolved mismatches remain reviewable.

### GAP-2026-018 — Baseline metrics omit scale/recovery invariants

- Category: observability / regression detection
- Severity: LOW
- Evidence: the prior snapshot omitted crawl outcomes/duration, direct/derived
  coverage, duplicate fact IDs, provenance omissions, retries, and task duration.
- Acceptance: expose each metric without persisting private runtime data in Git;
  deterministic tests and a production snapshot pass.
- Status: VALIDATED — the expanded snapshot records all listed metrics and reports
  no provenance omission, duplicate fact ID, retry, failure, or regression.

### GAP-2026-019 — Low role-verified named-contact coverage proves extractor failure

- Category: extraction / contact coverage
- Evidence: role-verified coverage is 11/211. Review of retrieved role-bearing
  pages found generic role prose, collective staff descriptions, or historical
  narrative rather than a systematic current name/title pattern missed by the
  extractor.
- Status: NOT_A_DEFECT
- Reason: association candidates are now visible separately; promoting them or
  extracting historical prose would reduce precision.

### GAP-2026-020 — Corporate redirect targets should be merged automatically

- Category: entity resolution / research
- Evidence: 138 attempts redirected across domains, often from legacy branch
  domains to location-specific Dignity Memorial URLs.
- Status: NOT_A_DEFECT
- Reason: collapsing branch URLs into one corporate domain would lose branch
  identity. A later evidence-resolution pass confirmed that exact network
  location pages can be crawled while retaining branch identity; corporate
  domains themselves are still never merged (see GAP-2026-023).

### GAP-2026-021 — Every audit event reparses the complete audit history

- Category: performance / observability
- Severity: LOW
- Evidence: scale repeat runs emit 422 events; `_audit` read and decoded the
  growing JSON file before every atomic replacement, dominating unchanged work.
- Root cause: audit history was treated as uncached external state despite the
  pipeline's file lock and single orchestrator owning a run.
- Acceptance: validate/load the audit list once per orchestrator; preserve atomic
  persistence and JSON compatibility; orchestration tests and scale timing pass.
- Status: VALIDATED — two 422-skip production repeats completed in 15.9 and 17.4
  seconds after eliminating repeated parsing; batching only unchanged skip events
  reduced the final 422-skip repeat to 2.4 seconds, with state-changing/failure
  events still immediately durable and no audit-format change.

### GAP-2026-022 — Duplicate source rows overwrite complementary location evidence

- Category: data integrity / provenance
- Severity: HIGH
- Evidence: controlled AFSA/CANA-shaped duplicate location rows show
  `build_crawl_queue` assigning the later row wholesale. A later empty email can
  erase an earlier address, phone, or email, while a newly supplied contact can
  inherit the wrong generic `source_url`.
- Root cause: location deduplication used dictionary replacement rather than the
  field-preserving merge already used for top-level leads.
- Acceptance: merge complementary nonempty fields; retain field-level source
  URLs; contact extraction uses the matching field source; regression tests.
- Status: VALIDATED — queue and extractor tests prove complementary fields and
  their distinct evidence URLs survive repeated-source ingestion.

### GAP-2026-023 — Safe location redirects are discarded with unsafe corporate redirects

- Discovered: 2026-08-24
- Category: research / entity resolution
- Severity: HIGH
- Evidence: 118 legacy business domains directly redirected to public Dignity or
  Arbor pages, many containing the listed branch name and city. The safe crawler
  correctly rejected every cross-domain redirect; corporate-domain merging would
  destroy branch identity.
- Root cause: redirect authorization had no provenance-backed location scope.
- Acceptance: explicit question; require direct homepage redirect plus strong
  name/location evidence; retain original entity; authorize only the exact page;
  reject sibling/weak matches; preserve SSRF controls and unresolved review.
- Status: VALIDATED — 115 location pages passed the tightened threshold and were
  fetched exactly. Radville/Weyburn and one weak Toronto candidate were rejected
  during adversarial review. A 15-record, eight-province sample matched fetched
  first-party titles and location evidence.

### GAP-2026-024 — Append crawl storage conflates organizations sharing one URL

- Discovered: 2026-08-24
- Category: data integrity / contact attribution
- Severity: HIGH
- Evidence: append storage keyed only by URL. Two Fletcher branch records
  targeting one page silently replaced each other; successful location recrawls
  also retained generic parent contact pages.
- Root cause: URL-only persistence identity and unscoped parent link discovery.
- Acceptance: key by organization plus URL; successful recrawl atomically
  replaces that entity's pages; retain prior evidence on failed retry; location
  resolution follows no generic parent links; regression coverage.
- Status: VALIDATED — shared URLs remain distinct in tests, stale entity pages
  are replaced, and all 115 production resolutions contain only their authorized
  page under the original entity identity.

### GAP-2026-025 — Crawlable-site quality findings lack research questions

- Discovered: 2026-08-24
- Category: automation / operator observability
- Severity: MEDIUM
- Evidence: the no-page input omitted 21 live finding/entity pairs on crawlable
  sites, including multi-location, shared-address, and email questions.
- Acceptance: union review-only entities into the durable run; map every current
  finding to a question; expose checked sources, outcome, confidence, and refusal
  reason; skip unchanged work.
- Status: VALIDATED — all 130 current finding/entity pairs have structured
  questions and the unchanged production repeat skipped 172/172 resolver tasks.

### GAP-2026-026 — Genuine ambiguities lack a durable finding-level decision workflow

- Discovered: 2026-08-24
- Category: operator workflow / auditability
- Severity: HIGH
- Evidence: 99 organizations retained 131 review-required findings after safe
  automatic resolution. Existing reviewed-domain replacement overwrote one
  domain decision and could not represent duplicate, address, email, or
  multi-location dispositions without mutating research inputs.
- Root cause: operator tooling exposed findings and research refusals but had no
  stable review-item identity, append-only decision history, or non-destructive
  eligibility interpretation.
- Acceptance: deterministic finding-level queue; append-only evidence-referenced
  decisions; idempotent exact repeats; visible conflicts; fail-closed duplicate,
  recrawl, and CRM-scope states; CLI list/show/decide/history/stats/apply;
  outcome metrics and regression tests; no entity/page/contact mutation.
- Status: VALIDATED — the scale queue deterministically contains 131 items across
  the same 99 organizations and is byte-identical on repeat. With no operator
  decisions, all 131 remain unresolved, 102 block CRM safety, and 131 block
  outreach. Focused tests cover history, idempotency, CLI behavior, sibling
  isolation, non-merging duplicate confirmation, and explicit eligibility.
