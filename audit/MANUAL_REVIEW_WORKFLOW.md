# Manual Ambiguity Review Workflow

The manual-review phase adds an auditable decision layer over existing quality
findings and research conclusions. It does not replace either source artifact.
Generated queue, decision, and effective-view files remain Git-ignored.

## Architecture

`review.manual.build_review_items` deterministically joins current quality
findings, research questions, and organization/location context. A review ID is
derived from organization ID, finding ID, and finding type. Repeated generation
does not create a new item or write decision history.

`ManualReviewStore` persists an append-only JSON decision ledger under a file
lock and atomic replacement. Every event snapshots what the operator saw,
including the original finding, research question, checked source classes,
refusal reason, candidates, and evidence references. Exact duplicate decisions
are idempotently skipped. A later different decision links to the prior event and
does not overwrite it.

`review_cli.py apply` writes a derived effective-review and readiness artifact.
It never changes enriched results, source findings, research history, pages,
contacts, organization identity, or CRM records. This repository has one JSON
backend for generated review artifacts; the unrelated CRM SQLite store is not a
second implementation of review decisions.

## Fail-closed dispositions

- Evidence-referenced current-relationship, distinct-organization,
  alternate-email, or false-positive decisions may resolve the corresponding
  finding in the derived view.
- A confirmed duplicate remains blocking because no transactional merge engine
  exists.
- A confirmed website relationship with no usable page remains blocking until a
  successful recrawl publishes evidence.
- A confirmed branch relationship remains blocking until an explicit CRM scope
  mapping exists.
- Rejected candidates/emails and deferred items remain reviewable.

These decisions are local evidence-backed dispositions. They are never training
signals and never alter `ResearchResolutionAgent`, crawler authorization,
quality thresholds, or global matching behavior.

## Scale validation

The 99 organization review queue generated 131 stable items across seven
provinces. Refreshing twice produced the same SHA-256 digest. With an empty
decision ledger, the effective view still contains 99 `NEEDS_REVIEW`
organizations: 131 unresolved items, 102 CRM blockers, and 131 outreach blockers.
Thus this phase introduces no synthetic review reduction.
