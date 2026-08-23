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
  usage. A real local EspoCRM instance covers live integration validation.

## Local Test Provisioning

The pinned, localhost-only Compose stack and live round-trip harness are under
`dev/espocrm`. Live validation completed on 2026-08-23 against EspoCRM 10.0.5
and MariaDB 11.8.8. Docker remained unavailable because its disabled service
required an interactive sudo password. An isolated rootless Podman store under
`/tmp` was used instead. The host's unavailable user systemd bus prevented the
Compose bridge's `aardvark-dns` process from starting, so the same pinned images
were launched with Podman's rootless `pasta` network and a shared network
namespace. Only `127.0.0.1:8080` and the test database port were published.

The API identity used API Key authentication and one role granting Account
create, read, and edit only. Delete, stream, assignment, user, message, export,
mass-update, and audit permissions were denied. Provisioning through the
authenticated EspoCRM REST API produced exactly one role and one API user.

The live evidence was:

- An unauthenticated API readiness request returned HTTP 401; authenticated
  administrator and API-key requests succeeded.
- Two consecutive syncs created then updated Account remote ID
  `6a8a9037cd3452fe3`; a complete second harness run returned the same ID and an
  exact website query found one Account.
- The Account website field round-tripped and each harness run recorded two
  local `SUCCEEDED` audit events in its temporary SQLite database.
- Deliberately invalid authentication and an unreachable loopback endpoint
  recorded `FAILED`/`EspoCRMError`, retained the local lead's `NEW`/`TEST`
  state, and returned only the generic `EspoCRM request failed` message.
- The API key was absent from container logs, tracked files, harness output,
  and local audit records. Runtime credentials remained ignored and mode 600.
- Remote cleartext URLs remained rejected; HTTP was accepted only for the
  existing loopback allowlist.

No synchronization runs implicitly. The operator must provide the instance URL,
API key, and an explicit `--domain` or `--all` command. No credentials are
committed. JSON and CSV exports remain supported external handoff mechanisms.
