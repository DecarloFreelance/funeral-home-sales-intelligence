# Canadian Scale Validation

Date: 2026-08-23

## Reproducible cohort

The first production-representative cohort combines the existing AFSA export
with a refreshed, target-provider-only CANA Canada export. It contains 342 raw
association locations, 257 website-bearing records, and 211 canonical domains
after exact normalized-domain deduplication. Forty-six duplicate website records
were consolidated while retaining provenance and branch locations. All ten
provinces are represented: AB 85, ON 56, BC 43, QC 37, SK 12, NS 11, MB 5, NB 4,
NL 1, and PE 1 location observations.

Runtime artifacts are stored under ignored `data/generated/scale/`; no public
contact dataset, crawl body, agent state, metric history, or CRM credential is
committed.

## Safe operating sequence

```bash
python cana_discovery.py --country Canada \
  --output data/generated/scale/cana_canada.json
python discovery_import.py \
  --source association=data/discovery_sources/afsa.json \
  --source association=data/generated/scale/cana_canada.json \
  --output data/generated/scale/crawl_queue.json
python website_crawler.py \
  --input data/generated/scale/uncrawled_queue.json \
  --output data/generated/scale/pages.json \
  --report-output data/generated/scale/crawl_report.json \
  --max-pages 4 --max-attempts 3 --timeout 5 --delay 0.25 \
  --append --resume
python lead_scoring.py \
  --input data/generated/scale/pages.json \
  --queue data/generated/scale/crawl_queue.json \
  --output data/generated/scale/scored_results.json
python run_enrichment.py \
  --pages data/generated/scale/pages.json \
  --results data/generated/scale/scored_results.json \
  --output data/generated/scale/enriched_results.json \
  --state data/generated/scale/agent_state.json \
  --audit data/generated/scale/agent_audit.json \
  --review data/generated/scale/review_queue.json
python generate_gap_metrics.py \
  --results data/generated/scale/enriched_results.json \
  --review data/generated/scale/review_queue.json \
  --state data/generated/scale/agent_state.json \
  --audit data/generated/scale/agent_audit.json \
  --crawl-report data/generated/scale/crawl_report.json \
  --output data/generated/scale/gap_metrics.json \
  --history data/generated/scale/gap_metrics_history.json
python build_research_queue.py \
  --queue data/generated/scale/crawl_queue.json \
  --pages data/generated/scale/pages.json \
  --report data/generated/scale/crawl_report.json \
  --output data/generated/scale/research_queue.json
```

The crawl command checkpoints atomically after every domain. `--resume` skips
both successful and failed terminal domains from the same bounded run. Refreshes
remain explicit; there is no uncontrolled recurring daemon, paid provider use,
or outreach action.

## Crawl and recovery evidence

- Reused evidence: 83 pages across 31 queue domains.
- Newly attempted domains: 180; successful 22; failed 158.
- New successful pages: 45; combined pages: 121 across 52 domains.
- Attempt outcomes: 45 success, 138 cross-domain redirects, 65 HTTP errors, 274
  request errors, and 18 fail-closed unsafe/unresolvable targets.
- No 429 response was observed.
- Measured new-domain runtime: 2,208,265 ms; average 12,268 ms; median 12,897 ms.
- A deliberate interruption after 56 checkpointed domains resumed with exactly
  124 remaining. No completed domain or page was duplicated.

The 158 failures remain in a generated research queue. Cross-domain corporate
redirects are not force-merged because branch identity would be lost.

## Enrichment, quality, and readiness

- Organizations: 211; facts: 3,257; fields: 25; mean facts: 15.4.
- Email: 64/211 (30.3%); phone: 207/211 (98.1%).
- Role-verified people and derived decision-maker candidates: 11/211 (5.2%).
- Distinct public directory candidates: 160/211 (75.8%), never promoted to a
  role-verified person.
- Verification states: 1,061 corroborated, 768 discovered, 499 metadata-valid,
  354 locally validated, 310 extracted, 186 DNS-valid, 76 inferred, and 3
  locally valid.
- Missing mandatory provenance: 0; duplicate fact IDs: 0; stale facts: 0;
  conflicted facts: 0.
- Review required: 172/211. CRM-safe: 45/211. Outreach-ready: 39/211.
- Findings: 159 no-website-evidence, 47 possible duplicate organizations, 21
  unresolved email-domain mismatches, 9 multi-location Account reviews, 8 shared
  addresses, 2 website-identity mismatches, and 1 first-party-confirmed
  cross-domain email.

All 159 zero-page records retain directory identity/contact evidence but carry
zero opportunity, lead-value, and executive-priority scores. None is CRM-safe.

## Accuracy and calibration sample

The deterministic review included high, low, blocked, uncrawled, independent,
corporate, and multi-location records:

- Beaverlodge and McCaw: high scoring with page evidence; McCaw's alternate email
  is explicitly first-party-published.
- Aquamations: the real address remains while `filler@godaddy.com` is rejected as
  a hosted-form placeholder.
- HPMcGarry and Martin Bros.: fetched website names materially conflict with the
  discovered identity and remain CRM-blocked.
- Dignity Memorial and Arbor Memorial: multiple named locations are preserved;
  CRM mapping is blocked pending network-versus-branch review.
- Acadia McKague's and Anderson Windsor: legacy domains redirect to location
  paths on a corporate site; they remain research records rather than being
  collapsed into the corporate domain.
- Essential Cremations, Grace Memorial, Reflections, and Southland role prose
  contains no safely paired current personal name. No name was inferred.

Scored website-backed records span 10.6–87.5 executive priority, with quartiles
48.8, 55.5, and 64.3. The 159 uncrawled records remain at zero and therefore do
not create false high-score outliers.

## Agent and CRM evidence

The first current-version pass completed 422 entity-agent tasks. The repeat pass
skipped all 422; retries and failures were zero, maximum attempts were one, and
recorded mean task duration was 145 ms. Caching the validated audit list once per
locked run removed repeated full-file parsing, then batching only unchanged skip
events under the pipeline lock reduced a complete 422-skip repeat to 2.4 seconds.
State-changing and failure audit events remain immediately durable. Partial publication protections remain
covered by the interruption/failure suite.

The localhost EspoCRM 10.0.5 instance synchronized three deterministic,
website-backed CRM-safe records spanning the score distribution: Mount Pleasant
Group, Fort McMurray Funeral Home, and Beaverlodge. Each was synchronized twice,
reused its remote ID, round-tripped its website, and produced two local success
events (six total). Blocked, uncrawled, and multi-location records were excluded.
The least-privilege API key was passed in memory and not logged or persisted.

## Stop boundary

An automatic recurring daemon is not justified: 158 unresolved identities need
bounded research or operator review, and immediate recrawling would repeat known
failures. The safe workflow remains explicitly invoked, resumable, and incapable
of sending outreach or invoking optional paid validation.
