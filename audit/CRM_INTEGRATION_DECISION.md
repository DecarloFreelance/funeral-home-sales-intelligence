# External CRM Integration Decision

Date: 2026-08-22
Status: User decision required

## Existing Guarantee

The local SQLite CRM is the auditable workflow source of truth. Lead upserts,
action deduplication, lifecycle transitions, and event history are implemented
and tested. Any external integration must synchronize from this state rather
than replace it or become an untracked alternate backend.

## Decision Required

Repository evidence does not identify an approved external CRM. Selecting
HubSpot, Salesforce, Zoho, a generic webhook, or another target changes all of
the following materially:

- Authentication and secret storage
- Company/contact/deal field mappings
- Upsert and external-ID semantics
- Conflict direction and retry behavior
- Rate limiting and batch size
- Sandbox/test-account requirements
- Whether action completion or only lead state is synchronized

Implementing one target without approval would create an unsupported public
behavior and potentially transmit private campaign data to the wrong service.

## Required Input

Choose the target CRM and authorize a sandbox/test account. The implementation
can then define a reviewed field mapping, idempotent outbound sync, local event
records for every attempt, bounded retries, and tests proving that failed remote
writes do not corrupt local state.

No credentials should be committed. Until a target is selected, existing JSON
and CSV exports remain the supported external handoff mechanism.
