# Canada Funeral Intelligence Platform — Project Plan

## Purpose

Build and maintain a unified, evidence-backed database of Canadian funeral-home locations using public and appropriately licensed sources.

The platform will preserve source provenance, normalize records, resolve duplicates, verify official websites, discover relevant pages, extract publicly listed staff and contact information, calculate confidence scores, and export clean datasets.

The funeral-home sector is the first vertical. Shared components should remain reusable for other Canadian business sectors.

## Core principles

1. **Provenance first** — retain every original source record, retrieval timestamp, source URL, external identifier, licence notes, and payload fingerprint.
2. **Locations are distinct** — separate parent organizations, brands, operating companies, and physical branches.
3. **Evidence-based decisions** — matches, merges, website selection, and extractions require evidence and confidence.
4. **Repeatable pipelines** — operations should be deterministic, testable, resumable, and idempotent where practical.
5. **Minimal dependencies** — use the Python standard library unless a dependency provides clear value.
6. **Respectful collection** — collect public business information, respect source terms, use bounded request rates, and avoid prohibited platforms.

## Repository architecture

```text
config/
data/
  raw/
  staging/
  processed/
  exports/
database/
  migrations/
  sqlite/
docs/
  architecture/
  sources/
  runbooks/
logs/
scripts/
src/canada_funeral_intel/
  collectors/
  normalization/
  deduplication/
  verification/
  extraction/
  scoring/
  storage/
  reporting/
  utils/
tests/
  fixtures/
  unit/
  integration/
```

## Phase 0 — Foundation

### Goal

Create the stable base required by all later phases.

### Deliverables

- typed environment configuration
- configuration validation
- structured logging
- SQLite connection and transaction helpers
- foreign-key enforcement
- deterministic migration engine
- migration history
- initial normalized schema
- lightweight typed models
- package CLI
- unit and integration tests
- README and architecture documentation

### CLI

```text
python -m canada_funeral_intel --help
python -m canada_funeral_intel config show
python -m canada_funeral_intel db init
python -m canada_funeral_intel db migrate
python -m canada_funeral_intel db status
```

### Initial schema

- source_datasets
- source_records
- organizations
- funeral_homes
- locations
- funeral_home_sources
- websites
- website_checks
- people
- person_evidence
- schema_migrations

### Completion criteria

- package compiles
- all tests pass
- migrations run repeatedly without duplication
- failed migrations roll back
- foreign keys are enabled on every connection
- tests use temporary databases
- CLI commands return useful exit codes

## Phase 1 — Source Registry

Create a registry describing government, regulator, association, open-data, commercial, and manually supplied sources.

Deliverables:

- source metadata models
- province and territory coverage
- source types and formats
- trust levels
- refresh intervals
- licensing notes
- enabled state
- validation
- deterministic seeding
- `sources list`, `sources show`, and `sources validate`

This phase stores metadata only and does not download or scrape records.

## Phase 2 — Import Framework

Import source datasets without altering original values.

Deliverables:

- CSV and JSON importers
- optional XML and HTML-table adapters
- import-run history
- raw payload storage
- payload fingerprints
- transactional imports
- row-level error reporting
- unchanged-record detection

## Phase 3 — Normalization

Normalize while preserving originals:

- business names
- addresses
- cities
- provinces
- Canadian postal codes
- phones
- emails
- URLs and domains
- French and English business terminology

Every normalized value records its normalizer name, version, timestamp, warnings, and source record.

## Phase 4 — Entity Resolution

Identify records representing the same organization or location.

Deliverables:

- deterministic match rules
- fuzzy candidate generation
- weighted scores
- manual review queue
- match evidence
- merge decisions
- merge history
- rollback support
- branch-aware matching

Important signals include licence number, phone, postal code, street address, normalized name, domain, city, and parent organization.

## Phase 5 — Website Discovery

Identify probable official sites and branch pages.

Deliverables:

- candidate websites
- provenance
- evidence-based confidence
- shared-domain handling
- branch-page handling
- alternate domains
- manual review queue

Do not scrape prohibited commercial map platforms or treat social profiles as official websites automatically.

## Phase 6 — Website Verification

Verify that candidate sites work and belong to the expected business.

Checks include:

- DNS
- TLS
- HTTPS and HTTP
- bounded redirects
- status code
- response time
- content type
- canonical URL
- soft 404
- parked or for-sale pages
- business identity match
- verification history

## Phase 7 — Page Discovery

Build a bounded, same-site crawler that prioritizes pages such as:

- about
- team
- staff
- people
- funeral directors
- professionals
- locations
- contact
- history
- management
- personnel
- équipe
- à propos

Exclude obituary archives, checkout flows, login pages, and other irrelevant sections by default.

## Phase 8 — Staff Intelligence

Extract publicly listed business staff information:

- name
- role
- location
- public business email
- public business phone
- biography URL
- profile image URL
- credentials
- evidence snippet
- evidence URL
- extraction timestamp
- extraction method
- confidence

Do not infer private personal details or treat obituary subjects as staff.

## Phase 9 — Contact Intelligence

Extract and classify:

- general emails
- department emails
- public staff emails
- phones
- fax
- toll-free numbers
- contact forms
- after-hours numbers
- location-specific contacts

## Phase 10 — Business Intelligence

Extract evidence-backed operating details such as:

- ownership type
- parent organization
- independent or chain
- years in operation
- languages
- service areas
- crematorium
- chapel
- reception facilities
- pre-planning
- livestreaming
- grief resources
- technology signals

## Phase 11 — Quality and Confidence

Calculate explainable, versioned scores for:

- source confidence
- identity confidence
- website confidence
- location completeness
- contact completeness
- staff completeness
- freshness
- evidence quality
- overall record quality

## Phase 12 — Reporting and Exports

Produce:

- CSV
- JSON
- SQLite snapshots
- coverage reports
- missing-site reports
- dead-site reports
- staff coverage
- source contribution
- duplicate review
- quality summaries

## Phase 13 — Refresh and Change Tracking

Support repeatable refreshes and historical changes:

- source changes
- new and closed locations
- website status changes
- domain changes
- staff additions and removals
- freshness
- historical snapshots
- change reports

## Phase 14 — Additional Verticals

Reuse the platform for other Canadian sectors by adding source definitions, rules, and vertical-specific detectors rather than duplicating the core platform.

## Development rules

Every phase must:

- preserve existing architecture
- stay within its assigned scope
- add migrations for schema changes
- add unit and integration tests
- compile successfully
- pass the complete test suite
- document new CLI behavior
- avoid temporary hacks
- avoid unnecessary dependencies
- report changed files and validation results

## Required validation

```bash
python -m compileall -q src tests
python -m pytest -q
python -m canada_funeral_intel --help
```

## Immediate next step

Implement and verify Phase 0 only. Phase 1 begins only after the foundation is complete and tested.
