# Implementation Feasibility Advisory

`ImplementationFeasibilityAgent` is a deterministic, internal-only advisor for
an already selected, evidence-bound commercial angle. It answers whether the
observed change is sufficiently bounded for a technical discovery conversation,
which implementation access remains unknown, how completion could be checked,
and what would force re-scoping.

It is downstream of `COMMERCIAL_ANGLE_SELECTED` and upstream of human review:

```text
retained first-party evidence
    -> COMMERCIAL_ANGLE_SELECTED
    -> ImplementationFeasibilityAgent
    -> internal advisory
    -> human operator
    -> existing review / pre-send / approval / guarded-draft workflow
```

The implementation adapts feasibility, CMS-dependency, and minimal-change
methods from external Agency-OS Markdown definitions. Those definitions are
design references only. They are not imported or executed, and no Agency-OS
orchestration or dependency is present in this repository.

## Operation

```bash
.venv/bin/python pilot_cli.py feasibility DOMAIN
```

The command reads the current organization, selected angle, enrichment facts,
form observations, and retained organization-owned pages. It writes only
generated/private task state and audit records under `data/generated/pilot/`.
It appends no pilot event and performs no network, CRM, outreach, form-submit,
or website-write action.

The advisory contains stable organization, pilot, angle, feasibility, evidence,
and input identities. Its task fingerprint covers the agent version, current
organization identity, selected angle and evidence, relevant form/technology
evidence, positive provider markers, and identity blockers. An unchanged input
is skipped; a material input or version change recomputes only that
organization's advisory. Orchestrator failure publishes no partial output.

## Classifications

Implementation path:

- `DIRECT_EDIT_LIKELY`: explicit retained evidence identifies organization-
  managed CMS access. A CMS signature alone does not qualify.
- `PROVIDER_CONTROL_LIKELY`: positive first-party markup identifies hosted or
  shared provider infrastructure. Provider confirmation remains required.
- `UNKNOWN_ACCESS`: retained evidence does not establish implementation control.

Scope:

- `NARROW`: one bounded component and an explainable before/after check.
- `MODERATE`: reserved for bounded work spanning multiple components.
- `UNSCOPED`: ownership, evidence, implementation boundary, or acceptance
  criteria are insufficient.

Outcome:

- `READY_FOR_DISCOVERY`: the selected observation supports a bounded discovery
  conversation; access and requirements still require human confirmation.
- `PROVIDER_CONFIRMATION_REQUIRED`: positive provider/shared-template evidence
  makes provider authority a prerequisite.
- `INSUFFICIENT_EVIDENCE`: no responsible implementation path can be stated.

Missing, foreign, stale, or materially changed evidence; changed organization
identity; and unresolved identity-critical findings fail closed. Unknown access
never becomes direct-edit likelihood merely because WordPress or another CMS is
detected.

## Authority boundary

The advisory is never customer-facing and cannot alter organization identity,
relationships, contacts, facts, research conclusions, quality findings,
CRM/outreach readiness, manual review, pre-send review, approval, lifecycle
state, `CONTACTED`, CRM records, drafts, messages, pricing, or customer sites.
It cannot approve contact or guarantee price, effort, access, feasibility, or
business impact.
