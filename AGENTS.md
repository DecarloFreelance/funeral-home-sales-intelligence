# Repository Automation Contract

Automated coding agents working in this repository must use `todo.md` as the
single work queue. Inspect current Git state, relevant implementation, tests,
generated quality findings, and audit evidence before choosing work.

For each evidence-supported task:

1. Select the highest-impact unblocked item whose prerequisites are satisfied.
2. Make the smallest change at the subsystem where the defect originates.
3. Run targeted outcome-based tests, including an adversarial case.
4. Run the broader suite before a logical checkpoint.
5. Inspect `git diff`, `git diff --check`, generated/private paths, and secrets.
6. Reconcile `todo.md` with evidence and commit a validated checkpoint.
7. Continue to the next actionable item without asking what to do next.

New tasks require concrete evidence such as a failed validation, provenance or
confidence violation, observed source format, entity-resolution defect,
idempotency/recovery failure, or other repository-local operational failure.
Record the evidence, impact, responsible subsystem, acceptance criteria, and
priority in `todo.md`. Do not add speculative features or cosmetic rewrites.

Stop only for a genuine product decision, missing credentials/billing/legal
authority, an unsafe or destructive action, an irresolvable external blocker, or
when no evidence-supported actionable work remains. Outreach sending remains an
operator-controlled action and is never authorized by this automation contract.

Runtime record agents use `run_enrichment.py`. Their filesystem scope is limited
to the explicitly supplied JSON inputs and generated state/output paths. They do
not receive general shell or network capabilities.
