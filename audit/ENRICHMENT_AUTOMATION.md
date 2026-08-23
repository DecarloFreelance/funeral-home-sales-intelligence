# Enrichment and Agent Automation Design

Date: 2026-08-23

## Architecture decision

Repository inspection found no reusable general agent registry or durable task
runner. Existing production flows use normalized JSON artifacts, bounded
record-level operations, atomic file replacement, and local audit records. The
enrichment workflow therefore extends those conventions. It does not replace
the operator UI's deliberately in-process crawl jobs or add a broker, scheduler,
ORM, or unrestricted autonomous network worker.

`lead_scoring.py` now performs deterministic enrichment after contact extraction
and before the scored record is finalized. `run_enrichment.py` supplies the
durable agent path for existing scored records:

1. `EnrichmentAgent` consumes one domain, its already-permitted crawled pages,
   business profile, and contact extraction.
2. `QualityControlAgent` consumes that enrichment plus validation/scoring data.
3. The orchestrator persists task state before execution and after each outcome.
4. A cross-record quality pass identifies possible duplicates and shared-address
   ambiguity without merging records.
5. Enriched records and a separate review queue are atomically published under
   `data/generated/enrichment/` for the operator UI.

The local evidence store remains authoritative. EspoCRM synchronization is not
expanded in this milestone because its current Account mapping has no reviewed
custom-field contract; raw evidence blobs are intentionally not sent to CRM.

## Evidence and confidence

Each fact includes a stable ID derived from entity, field, value, source URL,
detector, and detector version. Observation time is deliberately excluded from
the ID so refreshes replace the same logical observation rather than duplicating
it. Facts retain source, URL/type, timestamps, detector/version, confidence,
evidence, and a direct/derived flag.

States are progressive and distinct: `DISCOVERED`, `EXTRACTED`, `INFERRED`,
`CORROBORATED`, `LOCALLY_VALIDATED`, `EXTERNALLY_VERIFIED`, `CONFLICTED`, and
`NOT_CHECKED`. Multiple source URLs reporting the same direct value can promote
it to corroborated. Different values for the same field remain as separate
`CONFLICTED` facts. Derived role categories never masquerade as observed titles.

Changeable facts carry a `stale_after` timestamp. Quality control creates a
review finding after that horizon; it does not treat old data as current or
automatically recrawl the source.

## Recovery, caching, and boundaries

Agent tasks are keyed by domain and agent name. A versioned fingerprint of the
agent's actual inputs avoids repeating unchanged work and reuses the previously
persisted output. Changed input or detector version triggers a refresh. A task
written as `RUNNING` but found after restart becomes retryable `FAILED` work.
Failures are bounded by each agent's retry limit and stop the dependent chain.

Runtime agents have no shell capability, make no additional network requests,
and operate only on supplied crawl/result records. Audit events record agent,
version, entity, time, outcome, retry count, evidence count, and classified
errors. Secrets and raw private communication are neither inputs nor audit
fields.

Quality findings never silently mutate ambiguous business/contact attribution.
High-severity findings make CRM synchronization unsafe in the review artifact.
Outreach approval and sending boundaries are unchanged; the system still cannot
send email, SMS, calls, forms, or campaigns.
