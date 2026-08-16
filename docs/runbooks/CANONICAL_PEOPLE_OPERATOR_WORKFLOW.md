# Canonical People Operator Workflow

This workflow is explicit and manual. It does not make identity decisions
automatically.

## Source of truth and schema boundaries

The active canonical-people review table is
`person_observation_review_queue`. All `people-review` CLI commands, including
`populate`, `list`, `backlog`, and `decide`, operate on that table. The current
production path is:

```text
website extract-people
  -> website_page_person_observations
  -> people people-review populate
  -> person_observation_review_queue
  -> people people-review decide
  -> accepted observation
  -> people resolve
  -> people
  -> person_affiliations
  -> person_contact_points
  -> person_evidence
```

Developer warning: migration `0013_create_people_resolution.sql` contains
similarly named candidate-review objects. Do not select a table based only on
its name. For current canonical-people operations,
`person_observation_review_queue` is authoritative.

`person_resolution_candidates` is a **DEFERRED / UNIMPLEMENTED
CANDIDATE-RESOLUTION SCHEMA**. It currently has no production execution path:
there is no candidate generator, candidate repository or service,
candidate-review CLI, candidate-to-person resolver, or backlog integration.
Its pairwise observation structure, score/reason/priority/status fields,
`PersonCandidateRecord`, `PersonReasonCode`, and nullable
`person_evidence.resolution_candidate_id` indicate an unfinished design; they
do not guarantee a future implementation.

`person_review_queue` is **UNUSED CANDIDATE-SCHEMA RESIDUE**. It is not the
active observation queue:

```text
person_review_queue != person_observation_review_queue
```

`person_review_queue` is not used by `people people-review populate`,
`people people-review list`, `people people-review backlog`,
`people people-review decide`, or `people resolve`. Those commands use
`person_observation_review_queue`.

Neither dormant table is removed by this workflow. The candidate table is
referenced by nullable `person_evidence.resolution_candidate_id`, so any
removal requires an explicit future migration and deployment-compatibility
decision. Historical migration `0013_create_people_resolution.sql` must not be
rewritten to erase deployed schema history.

## 1. Extract website observations

Run the existing website staff extraction command for an approved website:

```text
canada_funeral_intel website extract-people --website-id WEBSITE_ID
```

This fetches eligible persisted website pages and stores immutable person
observations. Extraction does not approve an observation and does not create a
person review-queue row automatically.

## 2. Populate the person review queue

```text
canada_funeral_intel people people-review populate
```

This is an idempotent database-only operation. It creates one queue entry for
each observation that does not already have one.

Inspect workflow state with the read-only backlog command:

```text
canada_funeral_intel people people-review backlog
canada_funeral_intel people people-review backlog --details
```

The backlog distinguishes observations missing a queue row, pending, deferred,
rejected, accepted but unresolved, and resolved observations. The command
performs no network retrieval and does not mutate the database.

The existing queue listing is also read-only:

```text
canada_funeral_intel people people-review list
```

## 3. Decide each review entry

```text
canada_funeral_intel people people-review decide \
  --queue-id QUEUE_ID \
  --status accepted
```

Valid decisions are `accepted`, `rejected`, and `deferred`. Approval does not
create a canonical person and does not resolve the observation.

## 4. Resolve an accepted observation

```text
canada_funeral_intel people resolve --observation-id OBSERVATION_ID
```

Resolution remains an explicit operator action. For an accepted observation,
the existing resolver creates or reuses a canonical person and persists the
affiliation, public contact points, and evidence with the observation as
provenance. Pending, deferred, and rejected observations cannot be resolved.

Repeated resolution of the same observation is idempotent through the
existing evidence constraint and resolver behavior.

## 5. Optional canonical-person maintenance

If two canonical people require a separately justified merge:

```text
canada_funeral_intel people merge \
  --survivor-person-id SURVIVOR_ID \
  --absorbed-person-id ABSORBED_ID \
  --reason "documented reason"
```

An explicitly recorded merge can be rolled back once when the existing safety
checks permit it:

```text
canada_funeral_intel people rollback \
  --merge-id MERGE_ID \
  --reason "documented reason"
```

## Boundary conditions

- Crawler completion does not trigger staff extraction, review, or resolution.
- `website extract-people` does not imply approval.
- Review decisions remain manual and explicit.
- Approval does not imply canonical resolution.
- Resolution requires an accepted observation and an explicit `people resolve` command.
- The offline pipeline does not run website people extraction or resolution.
- No automatic identity matching or resolution is introduced by this workflow.
- Backlog and review-list commands are read-only and perform no network I/O.
- No raw page body is persisted by the people observation workflow.

People re-fetches record page-level network truth in the nullable
`website_pages.last_*` fields. `last_fetched_at` records completed probe state,
not extraction time; `last_success_at` is preserved across later failures;
`last_failure_at` is preserved as historical state across later successes; and
`last_content_hash` represents the latest successfully retrieved body. Raw
response bodies are not persisted. These fields currently do not suppress
network requests or provide caching. Website verification remains represented
by website-level `website_checks`, and batch retry state remains separate.
