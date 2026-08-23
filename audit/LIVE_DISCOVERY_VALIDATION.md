# Live Discovery Validation

Date: 2026-08-21

## Source

The Alberta Funeral Service Association public funeral-provider directory was
used as the first live discovery source.

## Directory Coverage

- Published member locations: 107
- Locations with websites: 70
- Valid normalized website domains: 52
- Website-linked locations retained after normalization: 69
- Invalid hostname rejected: 1 (`fostersgardenchapelcom`)

## Controlled Website Crawl

The live crawl ran in resumable batches with:

- Maximum 5 successful pages per domain
- Maximum 5 attempts per domain for later batches
- 10-second request timeout
- 0.25-second delay between requests
- Same-domain and same-brand redirect controls

Results:

- Domains with usable pages after reviewed replacement retries: 35 of 52
- Unique pages retained: 99
- Companies scored: 35

Unavailable domains were not bypassed. Causes observed include HTTP 403,
timeouts, unavailable hosts, and obsolete directory URLs.

## Contact Intelligence Results

- Companies with phone intelligence: 35 of 35
- Companies with email intelligence: 34 of 35
- Companies with named decision-makers: 10 of 35
- Named role records: 83

Directory-supplied contacts and locations were combined with website and
schema.org extraction. Generic navigation headings identified during review
were added to the person-name exclusion vocabulary.

## Validation

- Full live discovery scoring run completed successfully.
- Existing 18-company baseline scoring run remains functional.
- Automated tests: 35 passing.

## Research Queue Follow-up

Implemented after the initial validation:

- Structured per-URL crawl outcomes and failure reasons
- Atomic report persistence across appended batches
- Enriched research queue for all 21 unresolved domains
- 27 unresolved branch locations preserved in that queue
- Source provenance retained for all unresolved domains

Alternate-domain resolution is now implemented with a reviewed evidence ledger
and a reproducible queue applier. Of the original 21 research domains:

- 15 received medium- or high-confidence reviewed replacements
- 13 replacements are represented in the expanded crawl
- 2 replacements remain inaccessible and require manual verification
- 6 domains still have no reviewed replacement
- The active research queue has therefore been reduced from 21 to 8 records

The expanded crawl contains 99 pages across 35 scored domain groups. Resolution
records retain the old domain, replacement URL, confidence, rationale, and
evidence URL. The remaining queue distinguishes inaccessible reviewed
replacements from domains that still require research.

## Email Validation

Email intelligence now records auditable validation evidence without equating a
valid format with mailbox deliverability. In the expanded live dataset:

- Email addresses passing format validation: 61
- Addresses matching the crawled business domain: 39
- Recognized role accounts: 25
- Free-provider addresses: 1
- External-domain addresses flagged for review: 21
- Mailbox deliverability checks performed: 0

All 61 addresses explicitly report `deliverability: NOT_CHECKED`. A future
mailbox-verification integration can update that field without changing the
current result structure.

## Phone Verification

Phone intelligence now emits a verification record for every retained number,
including E.164 normalization, NANP format status, area-code region, risk flags,
and explicit external-verification state. In the expanded live dataset:

- Phone numbers assessed: 128
- Numbers passing NANP format checks: 128
- Locally usable numbers after risk checks: 127
- Alberta-area-code numbers: 120
- NANP numbers outside Canada or with unknown region: 8
- Placeholder-pattern numbers requiring review: 1
- Carrier, line-type, or reachability checks performed: 0

All 128 numbers explicitly report `reachability: NOT_CHECKED`,
`line_type: UNKNOWN`, and `carrier: NOT_CHECKED`. This prevents local format evidence from
being presented as proof that a number is currently connected.
