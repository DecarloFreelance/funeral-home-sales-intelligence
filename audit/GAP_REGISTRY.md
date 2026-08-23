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
