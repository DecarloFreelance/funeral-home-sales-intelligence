# External CRM Integration Decision

Date: 2026-08-22
Status: Decided — EspoCRM selected

## Existing Guarantee

The local SQLite CRM is the auditable workflow source of truth. Lead upserts,
action deduplication, lifecycle transitions, and event history are implemented
and tested. Any external integration must synchronize from this state rather
than replace it or become an untracked alternate backend.

## Decision

On 2026-08-22 the user selected self-hosted EspoCRM as the initial external CRM.
Its conventional Account model and REST API exercise a real integration while
keeping hosting and licensing under operator control. Additional backends may
later implement the same `CRMBackend` boundary.

The selected contract is:

- API-key authentication supplied only through `ESPOCRM_API_KEY`.
- Local leads synchronize to EspoCRM Accounts; canonical domain is mapped to
  `website`, contact values to `emailAddress` and `phoneNumber`, and local score
  and workflow state to an auditable description.
- The adapter searches by canonical website before first creation and persists
  the resulting remote ID for subsequent updates.
- Local SQLite state always wins; outbound failure cannot mutate the lead.
- Retries are bounded to transient HTTP failures. Every outcome is recorded in
  `external_crm_sync_events` without response bodies, credentials, or private
  exception messages.
- Deterministic fake backends cover automated validation without external API
  usage. Live instance validation remains environment-dependent.

## Local Test Provisioning

The pinned, localhost-only Compose stack and live round-trip harness are under
`dev/espocrm`. On 2026-08-22, provisioning was attempted with both installed
container runtimes. Docker was inactive and host administrative authentication
was unavailable; rootless Podman could not create its required user namespace.
The Compose model remains validated statically, but the live task must remain
open until a container runtime is enabled and a least-privilege API user is
created.

No synchronization runs implicitly. The operator must provide the instance URL,
API key, and an explicit `--domain` or `--all` command. No credentials are
committed. JSON and CSV exports remain supported external handoff mechanisms.
