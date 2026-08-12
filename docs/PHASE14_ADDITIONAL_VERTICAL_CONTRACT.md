# Phase 14 Additional Vertical Contract

## 1. Selected vertical

The first additional vertical is `cemetery`, displayed as “Cemetery and
Memorial Park”. The project plan names no ranked candidate, so cemetery is the
smallest adjacent Canadian service vertical: it shares organization/branch
relationships, public websites, location provenance, staff observations, and
reporting while avoiding a parallel crawler or sensitive personal-data model.

Scope is Canadian cemeteries, burial grounds, memorial parks, and cemetery
operators with a public business presence. Excluded are private burial plots,
individual memorial pages, obituary/tribute records, genealogical records,
funeral-home-only services, and unverified directory text.

## 2. Source strategy

The profile accepts source metadata from provincial/territorial registries,
municipal cemetery directories, cemetery associations, authoritative operator
records, and first-party operator websites. Registry and municipal sources are
authoritative for listed facilities; associations are authoritative only for
their published membership scope; websites provide supplementary operating
evidence. Sources may be exhaustive or partial and must declare that property
in source metadata. Absence from a partial source has no negative meaning.

Phase 14 adds no live source ingestion. Fixture metadata is used for tests.
Source-native identifiers remain raw in source records and are not interpreted
as person identifiers.

## 3. Entity and membership model

The existing `entities.entity_type` values `organization` and `branch` are
sufficient. A cemetery operator may have multiple branch/facility entities,
and an organization may participate in both funeral-home and cemetery
verticals. Vertical identity therefore does not belong in `entity_type`.

Migration 0019 adds generic `business_verticals` and
`entity_vertical_memberships`. Membership is an explicit, provenance-bearing
classification observation with a constrained confidence, method, version,
and optional source-record reference. A unique entity/vertical membership is
inserted idempotently; it never overwrites an existing classification. No
entity, parent, branch, website, or canonical person row is changed.

## 4. Normalization and identifiers

Existing business-name, address, phone, email, URL/domain, and people-name
normalizers are reused unchanged. Cemetery-specific license/provider
identifiers are not introduced in v1 because the plan and current sources do
not establish a common Canadian identifier vocabulary. Such identifiers remain
source-record fields until a regulator-specific contract exists.

## 5. Reused and profile-specific infrastructure

Website candidate discovery, verification, checks, review, primary selection,
shared-domain handling, page discovery, page identity, people observations,
canonical resolution, quality scoring, reports, and refresh tracking are
reused unchanged. The profile supplies page keywords and staff-role hints; it
does not fork the crawler or people table.

Generic page kinds remain `root`, `about`, `contact`, `locations`, `team`,
`staff`, `people`, `history`, and `other`. Cemetery vocabulary includes
`cemetery`, `memorial park`, `burial`, `interment`, `mausoleum`, `columbarium`,
and `grounds`. Existing funeral exclusions for obituary, memorial/tribute
records, testimonials, vendor content, and social links remain unchanged in
the funeral profile. A cemetery profile does not turn an individual memorial
page into a business page.

The cemetery role hints are `owner`, `operator`, `manager`, `administrator`,
`cemetery director`, `grounds manager`, and `registrar`. A role hint is not
credential proof and does not create or merge a canonical person.

No new cemetery-specific business facts are emitted in v1. Generic Phase 10
facts remain available only when their existing positive-evidence contract is
satisfied; there is no second fact engine and no automatic projection.

## 6. Quality, reporting, and refresh

`quality-confidence-v1` applies unchanged. The profile may define future
completeness expectations, but no new denominator or incomparable score is
added now. Phase 12 reports and Phase 13 refresh/change events remain generic;
vertical filters join through explicit memberships and never infer branch scope
from shared websites.

## 7. CLI and safety

The minimal new CLI is:

- `verticals list`
- `verticals show --vertical KEY`
- `verticals entities --vertical KEY`
- `verticals assign --entity-id ID --vertical KEY --actor ACTOR [--confidence N] [--source-record-id ID]`

Assignment is an explicit local classification operation, not automatic entity
resolution. All reads and registry output are deterministic JSON. No network,
social-media, private-data, production, website-review, person-review,
disposition, remediation, merge, or closure operation is part of this phase.

## 8. Required tests and deferred work

Tests cover deterministic profile registry, duplicate-key rejection, explicit
multi-vertical membership, provenance, idempotent assignment, invalid keys,
funeral regression behavior, cemetery role/page hints, shared-domain and branch
isolation, report/filter joins, migration idempotence, and read-only production
safety.

Deferred: live cemetery source ingestion, regulator-specific identifiers,
cemetery fact extraction, automatic classification, confidence calibration,
vertical-specific quality formulas, and additional verticals.
