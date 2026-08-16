# Website Acquisition and Batch Discovery Contract

Version: `website-acquisition-v1`

## Purpose

This layer turns existing source-provenance website signals into reviewable
website candidates and provides a separately authorized, bounded batch wrapper
around the existing website verification service. It does not decide which
website is canonical.

## Candidate sources and offline boundary

Offline candidate generation uses only normalized `url`, `domain`, and `email`
values attached to active entity source memberships. Source URLs are explicit
signals. Non-generic email domains are weaker inferred signals. Business-name
domain guessing, search engines, social lookup, and public crawling are not
candidate sources.

Every candidate retains entity ID, source-record provenance, normalized URL and
domain, discovery method, confidence, website kind/status, and evidence rows.
Population is idempotent on `(entity_id, normalized_url)` and never performs
DNS or HTTP.

## Network authorization and safety

Candidate population is offline and cannot enable network access. Verification
is a distinct `website batch-verify` command and requires `--allow-network`.
Dry-run never performs DNS or HTTP. All requests use the existing probe boundary:
HTTP(S) only, public-address DNS resolution, address pinning, TLS hostname
verification, bounded redirects, bounded response bodies, and per-request
timeouts.

Version-1 hard limits are: at most 25 entities, 2 candidates per entity, 1
sequential worker, 10-second timeout, 5 redirects, and 1 retry. CLI values above
these maxima are rejected. The default batch is smaller: 10 entities and 1
candidate per entity. No unlimited option exists.

## Shared domains and review

The same domain may be attached to multiple entities when each has independent
source provenance. A shared domain is marked `shared` and review-required; a
domain does not establish branch identity. Candidate population never assigns
`is_primary`, never approves/rejects review rows, and never changes entities.
Verification stores the existing `website_checks` result only. Existing shared
website identity behavior is preserved.

## Batch lifecycle and resume

`website_discovery_runs` records offline population or explicitly authorized
verification. Each selected website has one immutable run item. Run status is
`running`, `completed`, or `failed`; item status is `pending`, `running`,
`completed`, `failed`, or `skipped`. A completed item is not fetched again on
resume. Transient verification failures may be retried once; invalid URLs,
policy/DNS rejection, redirect-limit errors, and client errors are permanent.
An item failure does not erase successful items; the run is failed when any item
remains failed.

## Errors and outputs

Failures are classified as `invalid_input`, `policy_rejected`, `dns_failure`,
`timeout`, `connection_error`, `redirect_limit`, `http_client_error`,
`http_server_error`, `verification_error`, or `internal_error`. Stored details
are concise and contain no HTML or secrets. Outputs include `network_used`,
counts, deterministic method/status breakdowns, and checkpoint information.

## Production and future authorization

No production database is migrated or written by validation. A live pilot is a
separate authorization boundary. Before one is approved, the operator must
choose a development database, preserve the hard limits, and review the request
and failure logs. Page crawling and extraction are not part of this command.

## Page-discovery URL identity boundary

During one bounded page-discovery run, the requested URL is the request and
queue identity. The final URL after an actual redirect remains the durable
`website_pages.url` and `website_pages.normalized_url` identity. Discovery may
remember a validated same-site canonical URL as an in-memory alias for that
run, but it does not request the canonical URL merely because it appears in
page metadata and does not persist a canonical alias.

A successful redirect from a trusted requested URL to another host may add
that final host as a temporary trusted host alias for the current run. This is
redirect-proven provenance, not a general cross-domain permission. Arbitrary
external links, external canonical URLs, and ordinary subdomains remain
blocked. `www` and non-`www` forms continue to compare as the same domain for
same-site filtering.

There is no durable canonical-alias model yet. Cross-run canonical
deduplication, redirect-chain persistence, query-parameter normalization, and
`/index.html` normalization remain deferred.

## Page-fetch state boundary

Page discovery records page-level network truth in the nullable `last_*`
fields on `website_pages`. `last_fetched_at` is the time the completed probe
was recorded; it is not extraction time. A successful retrieval records
`last_success_at`, the response status/content type, and a deterministic
SHA-256 `last_content_hash`. A later failure preserves the previous successful
timestamp and content hash. A later success preserves `last_failure_at` as
historical failure state while clearing the current error.

Response bodies are never persisted. `website_pages.updated_at` retains its
existing discovery-row meaning and is not redefined as the last fetch time.
The page-fetch fields are updated by page discovery and explicit downstream
people or Business-Fact re-fetches, but they currently do not suppress or
skip network requests. No freshness policy or cache is implied.

`website_checks` remains website-level verification state, and batch
verification retry state remains in its existing run/item tables. Neither is
used as a page-fetch timestamp or merged into page-level retrieval state.

For file-backed databases, page-fetch state is committed through a dedicated
SQLite connection so a caller's work cannot be committed or rolled back by
the fetch-state writer. A caller connection with an active transaction is
rejected before mutation. Transaction-free `:memory:` connections use their
own transaction because SQLite cannot share an in-memory database through a
new connection; this fallback does not provide a separate connection's
durability. The repository's normal `connect_database()` file-path contract
is the supported configuration; URI-specific connection modes are not
reconstructed by the state writer.
