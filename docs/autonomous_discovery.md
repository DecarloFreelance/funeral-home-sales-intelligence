# Autonomous Canadian discovery

`discovery_cli.py` adds a bounded, checkpointed discovery layer above the
existing AFSA/CANA source collectors, normalized crawl queue, SSRF-safe crawler,
and evidence/enrichment pipeline. It never imports outreach, pilot, CRM, or form
submission code.

## Lifecycle and identity model

Search or directory observations enter as deterministic `DISCOVERED` candidate
records. They then move through identity verification and, only with retained
first-party evidence, to `ENRICHMENT_READY` and `PUBLISHED`. Side outcomes are
`DUPLICATE`, `QUARANTINED`, `REJECTED`, `STALE`, and `RETRYABLE_FAILURE`.
Search snippets are provenance, not identity proof.

An organization, location, and domain are separate concepts. A published
organization contains a location list and a referenced domain. Shared domains,
cross-brand redirects, and parent/location uncertainty enter the exception
queue instead of being merged. Existing seed domains are loaded idempotently.

## Unattended publication policy

Automatic publication requires a reachable normalized public website, strong
name overlap, matching discovered Canadian geography, funeral-service wording,
an explicit first-party identity marker, no cross-domain redirect, and no known
domain/organization conflict. The deterministic threshold is 0.85. Generic
directories and non-funeral sites are rejected. Weak names, geographic
conflicts, shared domains, and parent/location ambiguity are quarantined with
the underlying evidence required for review. A quarantined candidate cannot be
published unless a later verification pass supplies resolving evidence.

## Planning, budgets, and recovery

The gap-first planner emits deterministic province/territory and known-
municipality queries. Quebec receives English and French strategies. It does
not fabricate a municipality denominator: absent regions receive province- or
territory-wide queries. Identical completed queries are suppressed for 30 days.

Controls include query, candidate, verification-fetch, page, concurrency,
per-host-delay, retry, request-timeout, and runtime limits. State and the query
ledger are atomically checkpointed after every query. A nonblocking file lock
prevents overlapping scheduled runs. Exit code 0 is success, 3 means no search
provider was configured, and 4 means another process owns the lock.

The repository currently has no general search API integration or configured
credential. AFSA and CANA remain supported official directory collectors. The
execution command accepts an authorized JSON provider export; adding a live
provider means implementing the small `SearchProvider.search()` contract and
wiring existing environment-based credentials without logging them. Provider
results must remain candidates and need independently fetched first-party
verification.

## Commands

Inspect a bounded plan without writes:

```bash
.venv/bin/python discovery_cli.py autonomous --country CA --budget 20 --plan-only
```

Run a deterministic authorized export or fixture (canonical discovery state is
the only publication target):

```bash
.venv/bin/python discovery_cli.py autonomous --country CA --budget 20 \
  --max-candidates 100 --max-verification-fetches 40 \
  --search-export /path/to/authorized-search-results.json
```

Prove the same flow without canonical writes:

```bash
.venv/bin/python discovery_cli.py autonomous --country CA --budget 20 \
  --search-export /path/to/authorized-search-results.json --dry-run
```

Inspect coverage, backlog, quarantine, query use, and novelty:

```bash
.venv/bin/python discovery_cli.py autonomous-status
```

Recommended periodic invocation after an authorized provider adapter/export is
available:

```bash
.venv/bin/python discovery_cli.py autonomous --country CA --budget 20 --max-candidates 100 --max-verification-fetches 40 --max-runtime 1800 --search-export /path/to/authorized-search-results.json
```

Cron/systemd may invoke that command, but this repository does not install or
enable a scheduler. Increase budgets gradually after inspecting yield and quota
usage in `data/generated/autonomous_discovery/report.json`; lower any limit to
reduce work. Structured state and reports are under that ignored generated
directory.

## Saturation and revalidation

The report measures novel verified organizations per query, duplicate rate,
and segment yield. A segment can be labeled
`DISCOVERY_SATURATED_UNDER_CURRENT_STRATEGIES` only after the configured number
of low-yield query batches. This is not a national completeness claim. Query
entries become eligible after their 30-day `stale_after`; candidate identity
evidence defaults to a 90-day horizon. Revalidation should prioritize stale or
failed identities, newly corroborated quarantine records, and low-coverage
regions rather than recrawling everything.

Review `review_queue` reasons and retained name, geography, relevance, redirect,
and observation evidence. Human intervention is intended only for these
exceptions, not every high-confidence candidate.
