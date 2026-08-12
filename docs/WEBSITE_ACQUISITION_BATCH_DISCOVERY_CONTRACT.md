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
