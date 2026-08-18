# Canada Funeral Intelligence — Operational Task List

This is the working checklist for turning the current operator workflow into a
repeatable, evidence-preserving pipeline. Completed items are recorded here so
future sessions can resume from the first unchecked item.

## Completed

- [x] Website verification and bounded crawling.
- [x] HTTP crawling with optional Playwright fallback.
- [x] Persisted page metadata and fetch-state observability.
- [x] People extraction and provenance-backed observations.
- [x] Business-fact extraction and provenance-backed observations.
- [x] Approved-website batch processing:
  `website process-approved`.
- [x] People review queue population and backlog reporting.
- [x] Safe deterministic people auto-triage (`--apply-safe` only rejects or
  defers; it does not accept or resolve people).
- [x] Recommendation-only agent review with NVIDIA, OpenRouter, and OpenAI
  provider adapters.
- [x] Task-specific agent profile defaults in `config/agent_profiles.json`.
- [x] Manual/API-assisted cleanup and resolution of the first 18 people.
- [x] People CSV and audit exports under `exports/`.
- [x] Removed the temporary `fanout.txt` file.
- [x] Added an opt-in Bash task-list helper at
  `scripts/tasklist-prompt.bash`; reminders are now fully manual so they never
  interrupt command input.

## Next implementation queue

### 1. Finish the agent framework

- [x] Make `people-review` validate a strict response schema before accepting
  recommendations.
- [x] Add required disposition, confidence, cleaned name, rationale, and
  evidence-reference fields.
- [x] Reject malformed, incomplete, or unsupported model output without
  changing the database.
- [x] Add retry/backoff, timeout, and provider error reporting to the output
  artifact. All three review agents now retry transient failures and preserve
  terminal provider errors in a JSON artifact without changing the database.
- [x] Record model/provider/profile metadata and prompt version in every
  artifact.
- [x] Complete a live NVIDIA dry run for the remaining deferred people; all
  seven recommendations were returned with `database_changed: false`.

### 2. Add the business-facts agent

- [x] Load stored business-fact observations rather than people observations.
- [x] Ask the model to classify each fact as keep, flag, or reject.
- [x] Require the recommendation to cite the stored source URL, page ID, fact
  key, and evidence snippet.
- [x] Keep the first version recommendation-only; no automatic fact deletion.
- [x] Add a separate review/apply command with an explicit confirmation flag
  after the dry-run format is proven. Applied recommendations are stored as an
  immutable audit run; source facts are not deleted or overwritten.

### 3. Add the website-quality agent

- [x] Load verification, crawl, page-fetch, identity, and content-limited
  signals for approved websites.
- [x] Produce a per-website quality classification: usable, limited, blocked,
  duplicate/shared-domain, or needs retry.
- [x] Recommend the next acquisition method: HTTP, Playwright, targeted page,
  or manual/source lookup.
- [x] Keep recommendations read-only and exportable as JSON/CSV.
- [x] Persist validated website-quality recommendations as an auditable run;
  website records remain unchanged.

### 4. Improve batch operations

- [x] Add persisted pipeline-run records with start/end time, command options,
  per-website status, and error details. Existing `pipeline_runs`,
  `pipeline_run_stages`, `pipeline_run_errors`, and website discovery run-item
  tables provide this audit trail.
- [x] Add `--resume`/retry behavior that skips successful unchanged work.
  Pipeline resume skips completed stages, and website verification resume skips
  completed website items while retrying eligible failures.
- [x] Add bounded concurrency with per-host rate limits. Network verification
  supports `--max-concurrency` with serialized SQLite persistence, persisted
  batch settings, and a thread-safe `--host-delay` limiter.
- [x] Add a concise progress view so long runs do not appear frozen. Website
  batch verification supports opt-in `--progress` status lines on stderr.
- [x] Add a report for blocked/content-limited sites requiring alternate work.
  Use `website quality-blocked-report` for a read-only grouped report.

### 5. Improve extraction quality

- [x] Add business-fact service-area boundary filtering for sentence fragments,
  navigation text, and malformed community names, with regression coverage.
- [x] Re-extract affected sites after the filtering change and audit the new
  business-fact observations; v5 was applied successfully with 263 facts.
- [x] Tighten service-area extraction for pipe-delimited contact blocks,
  numeric historical fragments, and truncated trailing tokens; regression tests
  pass.
- [x] Exclude agent-audited rejected business facts from operational summaries
  while preserving the underlying observations and audit trail.
- [x] Fix name-boundary extraction for role suffixes and paired names such as
  `Wade & Kelly Lumbard` and `Jack & Joyce Lumbard`.
- [x] Reduce page-heading, contact-block, article-author, and historical-noise
  candidates before they enter the review queue; add regression coverage for
  the Brockie-Donovan and Bardal examples.
- [ ] Preserve the raw observation while storing cleaned values separately.
- [ ] Add regression fixtures for the Brockie Donovan and Bardal examples.

### 6. Coverage and delivery

- [x] Expand the curated directory export with reviewed business facts and
  accepted people names/roles while excluding contacts, raw evidence, and
  unresolved records.
- [ ] Configure real hosting-level access control for the research site
  (GitHub Enterprise Cloud private Pages or an authenticated proxy).
- [ ] Review the seven deferred observations and decide whether they belong in
  current-person reporting or historical ownership reporting.
- [ ] Re-export people after each accepted resolution batch.
- [x] Build a coverage report by province, website status, people status, and
  business-fact status.
- [ ] Add authoritative source coverage for remaining jurisdictions.
- [ ] Keep public-directory output separate from unresolved or historical
  records.

## Operating rules

- Agent calls are recommendation-only by default.
- No model may accept, reject, resolve, merge, or delete records without an
  explicit operator command and an auditable note.
- Every recommendation must retain its source URL/page ID and evidence.
- Never read, print, commit, or export API keys. Use environment variables or
  the existing key-file adapter without exposing contents.
- Treat HTTP 403, identity score 0, and one-page crawls as acquisition-status
  signals, not proof that a business is invalid.

## Shell task-list reminder

Load the manual reminder function for the current shell:

```bash
source scripts/tasklist-prompt.bash
```

Do not add this script to `PROMPT_COMMAND` or source it automatically from
`~/.bashrc`; that can interrupt multi-line command entry.

```bash
source "$PWD/scripts/tasklist-prompt.bash"
```

For an explicit reminder between command sequences, run:

```bash
cfi_tasklist_remind
```

## Validation checklist after code changes

```text
.venv/bin/ruff check src tests
.venv/bin/python -m compileall -q src tests
.venv/bin/pytest -q
git diff --check
```

## Immediate next command

After implementing or changing an agent, run the focused tests first, then a
dry-run artifact:

```text
.venv/bin/pytest -q tests/integration/test_business_facts_phase10.py
```

```text
python -m canada_funeral_intel people people-review agent-review \
  --agent people-review \
  --output exports/people-review-dry-run.json
```

Then inspect the artifact before any apply/resolution command.
