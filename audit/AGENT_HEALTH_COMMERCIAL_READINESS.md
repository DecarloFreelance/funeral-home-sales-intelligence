# Agent Health, Pipeline Integrity, and Commercial Readiness Audit

Audited 2026-08-24 from `main` at `5991746` (the checkout had advanced from the
requested `34fa3ee` checkpoint through the validated manual-review workflow).
This audit used the 211-organization scale artifacts and made no network, CRM,
or outreach write.

## Runtime and dataflow map

The production path is a sequence of explicit, resumable commands rather than a
single daemon:

`AFSA/CANA/manual imports -> normalized crawl queue -> safe crawler -> scoring
and contact extraction -> EnrichmentAgent -> QualityControlAgent ->
ResearchResolutionAgent -> manual review -> metrics -> commercial-readiness
presentation -> optional local CRM -> explicitly configured EspoCRM`.

All generated evidence, task state, audit events, research results, review
decisions, and commercial outputs remain under ignored `data/generated/`.
SQLite is used only for operator action/CRM state and Espo mappings. No second
agent-evidence storage backend exists, so backend parity is not applicable;
tests instead cover the filesystem/SQLite boundary semantics independently.

Supported command entrypoints found by CLI dispatch or intentional top-level
execution are:

- discovery/crawl: `afsa_discovery.py`, `cana_discovery.py`,
  `manual_import.py`, `discovery_import.py`, `website_crawler.py`,
  `build_research_queue.py`, and `apply_domain_resolutions.py`;
- analysis/agents: `lead_scoring.py`, `run_enrichment.py`,
  `run_research_resolution.py`, `generate_gap_metrics.py`, `verify_audit.py`,
  `audit_client_sites.py`, and `commercial_readiness.py`;
- operator/review: `flask --app operator_ui.app`, `review_cli.py`, and the
  operator-invoked CRM action services;
- CRM: `outreach_export.py`, `espocrm_sync.py`, and
  `validate_espocrm_live.py`;
- separate platform/reference workflows: `platform_candidate_import.py`,
  `rank_platform_candidates.py`, `build_platform_outreach.py`,
  `rank_package_buyers.py`, `generate_example_report.py`, and the explicitly
  preserved scripts under `legacy/reference_campaign/`.

No runtime plugin/registry or dynamic agent factory was found. Agent membership
is explicit in the two orchestrator construction sites, so registration cannot
hide an untraced agent.

## Component health matrix

| Component | Implementation / production entry | Input -> durable output -> consumer | Failure / idempotency | Health |
|---|---|---|---|---|
| AFSA discovery | `discovery/providers/afsa.py`, `afsa_discovery.py` | public directory -> source JSON -> ingestion | bounded requests; deterministic provider tests | VERIFIED_ACTIVE |
| CANA discovery | `discovery/providers/cana.py`, `cana_discovery.py` | public directory -> source JSON -> ingestion | bounded requests; deterministic provider tests | VERIFIED_ACTIVE |
| Source normalization | `discovery/ingestion.py`, `discovery_import.py` | source rows -> canonical queue -> crawler | invalid/private targets rejected; domain/location merge is idempotent | VERIFIED_ACTIVE |
| Network safety | `discovery/network_safety.py` | URLs/DNS -> authorization decision -> crawler | private/loopback/redirect targets fail closed | VERIFIED_ACTIVE |
| Priority crawler | `discovery/crawler.py`, `website_crawler.py` | queue -> organization-keyed pages/report -> scoring/research | checkpointed, resumable, bounded, failed recrawls retain prior evidence | VERIFIED_ACTIVE |
| Contact extractor | `extraction/contact_extractor.py` via `lead_scoring.py` | pages/directory evidence -> contacts/sources -> enrichment/scoring | malformed content bounded; attribution retained | VERIFIED_ACTIVE |
| Email validator | `intelligence/email_intelligence.py` | public email -> local/DNS evidence -> quality/contact facts | optional provider failure remains not checked; no mailbox claim | VERIFIED_ACTIVE |
| Phone validator | `intelligence/phone_intelligence.py` | public number -> metadata evidence -> quality/contact facts | optional provider failure remains not checked; no reachability claim | VERIFIED_ACTIVE |
| Legacy scoring | `lead_scoring.py`, `scoring.py`, `feature_detector.py` | pages/queue -> scored result -> agents/operator | zero-page fail closed; deterministic; many sales labels remain internal-only | ACTIVE_WITH_GAP |
| EnrichmentAgent | `automation/agents.py`, `run_enrichment.py` | scored record + owned pages -> durable facts/task/audit -> QC/operator/metrics | atomic publication; retry limit; fingerprint skip | VERIFIED_ACTIVE |
| QualityControlAgent | same entrypoint, `enrichment/quality.py` | durable facts/contact/scoring -> findings/readiness -> research/review/CRM gates | exceptions abort publication; unknown state never approves | VERIFIED_ACTIVE |
| Dataset quality | `evaluate_dataset_quality` in `run_enrichment.py` | all records -> cross-entity findings -> review/research | never chooses a winner or merges | VERIFIED_ACTIVE |
| Agent orchestrator | `automation/orchestrator.py` | per-entity context -> state/output/audit -> later stages | interrupted work recovered; partial failures not returned; unchanged skip | VERIFIED_ACTIVE |
| ResearchResolutionAgent | `research/resolution.py`, `run_research_resolution.py` | explicit findings + retained crawl evidence -> questions/conclusions/queue | only strong location matches resolve; ambiguous remains unresolved | VERIFIED_ACTIVE |
| Manual review | `review/manual.py`, `review_cli.py` | findings/research -> stable queue + append-only decisions -> effective readiness | no merge/page/contact movement; exact decisions idempotent | VERIFIED_ACTIVE |
| Metrics/regression | `automation/metrics.py`, `generate_gap_metrics.py` | results/state/audit/review -> snapshots -> gap review | repeated identical snapshot not duplicated | VERIFIED_ACTIVE |
| Operator UI | `operator_ui/` | generated JSON + SQLite -> local views/actions | CSRF/confirmation gates; malformed files render empty | ACTIVE_WITH_GAP |
| Local CRM/action queue | `crm/database.py`, `crm/action_queue.py`, `crm/execution.py` | explicitly safe record -> SQLite lead/action/events -> operator/Espo | transactions and active-action dedupe; explicit readiness now required | VERIFIED_ACTIVE |
| EspoCRM adapter | `crm/espocrm.py`, `crm/sync.py`, `espocrm_sync.py` | approved local lead -> Account/mapping/audit -> EspoCRM | HTTPS/loopback policy, escaped IDs, bounded retry, failed writes isolated | EXTERNAL_DEPENDENCY_BLOCKED |
| Platform candidate workflow | `platform_candidate_import.py`, `rank_platform_candidates.py`, `build_platform_outreach.py` | separate candidate sources -> ranked drafts -> operator approval | separate from client leads; drafts stay unsent | VERIFIED_ACTIVE |
| Legacy LeadIntelligence/export | `intelligence/lead_intelligence.py`, `outreach_export.py` | scored results -> local CRM/action/CSV | now filters on explicit current quality approval | ACTIVE_WITH_GAP |
| Commercial presentation | `commercial_readiness.py` | enriched results + owned pages -> internal shortlist/prototypes | deterministic, read-only, safe-record-only, evidence referenced | VERIFIED_ACTIVE |
| Feature audit printer | `verify_audit.py` | pages -> console feature evidence | read-only; not an invariant verifier | VERIFIED_ACTIVE |
| Client-site audit utility | `audit_client_sites.py` | separately supplied client pages -> client report | isolated from production cohort | WIRED_BUT_UNVERIFIED |
| Historical report generator | `generate_example_report.py`, `report.py`, `ai_audit.py` | legacy scoring -> report/console | can overstate missing/revenue opportunities; not customer-safe | OUTPUT_UNUSED |
| Empty placeholders | `exporter.py`, `revenue.py`, `prompts.py` | none | no production caller (including dynamic/CLI search) | DEAD_CODE_CANDIDATE |

`ACTIVE_WITH_GAP` does not mean unsafe data is allowed through the current
pilot path. The operator UI does not yet present the new finding-level manual
decision CLI, and the legacy scoring/export representation contains internal
sales heuristics. The commercial presentation deliberately bypasses those
claims and consumes current evidence plus quality gates.

## Production trace and contract evidence

Representative records were selected by stable finding/outcome categories:

- `acadiamckaguesfuneralcentre.com`: recovered first-party network location,
  original entity retained, one owned page, 21 facts, no finding, safe/ready.
- `martinbros.com`: wrong-site identity and alternate email evidence retained;
  both identity/attribution findings block readiness.
- `ccmwfuneralhome.net`: duplicate candidate remains distinct and blocked.
- `connelly-mckinley.com`: multi-location, shared-address, and email questions
  overlap; no evidence is moved across organizations and readiness is blocked.
- `arbormemorial.ca`: no usable location-scope page plus duplicate/multi-location
  ambiguity remains blocked.

For every record the durable agent state contains separate
`<domain>:enrichment` and `<domain>:quality_control` entries. Research candidates
also contain `<domain>:research_resolution`. New contract tests prove persisted
enrichment is the representation consumed by quality/commercial presentation,
facts retain source URL/time, sibling pages remain isolated, unresolved research
never becomes confirmed, and partial failure raises without returning a record.

The unchanged production rerun processed 211 records and skipped all 422
enrichment/QC tasks. Research processed 172 candidates and skipped all 172
tasks; results remained 245 questions, 116 resolved and 129 unresolved.

## Failure-mode and storage results

The targeted suite exercised timeout/request failure, DNS failure, SSRF and
redirect rejection, malformed inputs, resolver ambiguity, agent exception,
interruption/recovery, retry exhaustion, Espo authentication/runtime failure,
escaped remote IDs, SQLite transaction rollback, manual-review idempotency, and
sibling-location isolation. All failed closed. The injected multi-agent failure
left completed task evidence and a visible failed task/audit event but returned
no partially published record.

The audit found and fixed one cross-storage defect: the reachable legacy
`outreach_export.py` path could write records without current quality approval,
and old SQLite actions/records had no durable readiness flags. SQLite now stores
`crm_sync_safe` and `outreach_ready`; absent values migrate to false. Export,
action execution, individual Espo sync, and `--all` Espo selection require the
appropriate explicit approval. Existing unsafe rows remain visible but cannot
start/sync.

## Commercial signal safety

| Class | Signals | Customer interpretation / risk |
|---|---|---|
| CUSTOMER_SAFE | positively observed services, public social/careers URLs, fetched website URL, public contact values | Present as observed at the cited URL/time. Email DNS and phone metadata must not be described as mailbox/line reachability. |
| CUSTOMER_SAFE_WITH_WORDING | technology HTML signatures; a feature not detected across the retained bounded page set; inferred role category | “Observed”, “our bounded scan did not detect”, and “candidate based on the observed title”. Dynamic/unscanned pages create false-negative risk. |
| INTERNAL_ONLY | executive/sales priority, contact-confidence arithmetic, quality finding codes, research confidence, shortlist rank, CRM/outreach readiness | Useful for triage and safety, not an external claim or an “AI score”. |
| NOT_RELIABLE_ENOUGH | revenue opportunity score/tier, missing-feature absolutes, generic target role, generated pain points/packages/pitches, causal conversion claims | Legacy heuristics lack evidence sufficient for customer presentation. Do not publish. |

The minimal scorecard therefore has separate, deterministic dimensions rather
than one customer-facing score: explicit identity/readiness gate, observed
reachability evidence, page-scan scope, positive capabilities, carefully worded
not-detected opportunities, and evidence strength. The numeric shortlist score
is internal-only and ranks contactability, traceability, and bounded opportunity
count after both safety gates pass.

## First-pilot shortlist and prototypes

`python commercial_readiness.py` produced 25 eligible internal candidates and
five prototypes in ignored
`data/generated/scale/commercial_readiness.json`. No CRM or outreach write
occurred. The top candidates were:

1. `foothillsmemorialchapel.com`
2. `beaverlodgefuneralservice.com`
3. `gregorysfuneralhomes.com`
4. `fernhillcemetery.ca`
5. `cornerstonefuneralhome.com`
6. `missionview.ca`
7. `bowvalleyfuneral.ca`
8. `essentialscbs.com`
9. `mccawfuneralservice.com`
10. `evergreenfh.ca`
11. `fostermcgarvey.com`
12. `gracememorial.com`
13. `peacevalleyfuneral.ca`
14. `carnells.com`
15. `essentialcremations.com`
16. `southlandfuneral.com`
17. `rafuneralservices.com`
18. `arbormemorial.com`
19. `brenansfh.com`
20. `burgarfuneralhome.com`
21. `cooksouthland.com`
22. `everdenrust.com`
23. `hannafuneral.ca`
24. `saamis.com`
25. `aquamations.ca`

Each generated entry includes selection reasons, public contact facts,
organization-specific scanned URLs, evidence fact IDs, confidence state, and
carefully worded opportunities. The prototype entries correspond to the first
five and explicitly prohibit revenue/ranking/compliance/causality claims.

## Gaps and verdict

- **BLOCKER:** none for a tightly controlled, operator-reviewed first pilot.
- **IMPORTANT:** legacy scoring/report language is not customer-safe and the web
  UI does not expose finding-level manual decisions; use the evidence-backed
  commercial output and CLI review workflow for the pilot.
- **OPTIONAL:** consolidate legacy scoring/report fields and expose the manual
  review/commercial package in the web UI after pilot feedback.
- **EXTERNAL:** EspoCRM requires the already documented local runtime/API key;
  ZeroBounce and Twilio remain optional paid enhancements.
- **MANUAL:** 99 organizations / 131 findings require evidence-backed operator
  judgment; every prototype claim should receive operator source review before
  personalized outreach. Sending remains explicitly operator-controlled.

Verdict: **CONTROLLED PILOT READY**. The canonical agents are functioning and
the current evidence can safely identify a first cohort, provided only the new
evidence-backed presentation is used and an operator verifies claims before any
separately authorized outreach.
