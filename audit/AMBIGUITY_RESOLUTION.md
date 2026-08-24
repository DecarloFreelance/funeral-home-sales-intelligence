# Ambiguity Resolution Validation

Validated on 2026-08-24 against the reproducible 211-organization Canadian
scale cohort. Generated public crawl bodies, runtime state, and audit data remain
Git-ignored.

## Resolution contract

`ResearchResolutionAgent` receives one entity plus explicit quality findings. It
records the question, current evidence, candidate source classes, conclusion,
confidence, resolver version, timestamp, and refusal reason. The existing
orchestrator supplies atomic publication, bounded attempts, recovery state, and
fingerprint idempotency. Review-only entities are included even when crawlable.

Identity-critical recovery requires a direct homepage redirect from the listed
business domain to a public network location URL, matching distinctive name
evidence and either geography or multiple name tokens. Arbor named branch pages
require the full distinctive name. The original domain stays the entity key.
Only the exact location page is authorized; parent contact/about pages are
excluded. Every request and redirect retains public-network authorization.

No automatic merges, lifecycle changes, parent/branch reassignment, contact-scope
promotion, CRM synchronization, or outreach occur. Insufficient evidence returns
`REQUIRES_REVIEW`.

## Production evidence

- Before: 172/211 review-required; 159 no-website; 45 CRM-safe; 39 outreach-ready.
- Queue: 172 candidates and 245 finding-specific questions.
- Resolved: 115 exact location pages plus one existing directly published
  cross-domain email confirmation.
- Unresolved: 129 questions across duplicate, address, multi-location, email,
  and unavailable/weak website evidence.
- After: 99/211 review-required; 44 no-website; 122 CRM-safe; 112 outreach-ready.
- Evidence: 4,648 facts, zero missing provenance, duplicate fact IDs, stale facts,
  agent failures, or detected metric regressions.
- Idempotency: enrichment skipped 422/422 unchanged tasks; research skipped
  172/172 unchanged tasks.

An early pass accepted a Radville record's redirect to the similarly named
Weyburn branch and a weak single-token Toronto match. Adversarial review tightened
the threshold and returned both to manual review. URL-only append storage also
allowed organizations sharing a network URL to overwrite each other; persistence
now keys organization plus URL, and successful recrawls replace only that
entity's pages. Both failure modes are regression-tested.

## Accuracy and remaining ambiguity

Fifteen deterministic resolutions across AB, BC, MB, NB, NS, ON, QC, and SK were
checked against fetched first-party page title, target path, association identity
and location, and redirect evidence. All 15 supported the location-page result.
All 115 authorized targets returned usable HTML and retained the original entity.

The remaining 99 review records are not defects merely because they remain open.
Finding categories overlap: 44 no-website, 47 possible-duplicate, 21 email-domain,
nine multi-location, eight shared-address, and two website-identity findings.
Structured research entries explain why automation refused and which source
classes were considered.
