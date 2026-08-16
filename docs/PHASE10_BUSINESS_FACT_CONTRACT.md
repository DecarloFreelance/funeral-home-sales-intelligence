# Phase 10 Business Fact Contract

## 1. Purpose

Phase 10 records evidence-backed operating facts stated by first-party funeral-home website pages. Facts are observations for reporting and later review; they are not canonical entity, website, branch, person, or identity decisions.

## 2. Scope

Version 1 covers eight conservative fact keys:

| Fact key | Kind | Meaning |
| --- | --- | --- |
| `ownership_type` | enum | An explicitly stated ownership or operating model. Values: `independent`, `family_owned`, `employee_owned`, `corporate`, `cooperative`, `nonprofit`. |
| `parent_organization` | text | An explicitly named parent, group, or operating organization. |
| `founded_year` | integer | An explicitly stated founding/opening year. |
| `languages_offered` | multi_text | Languages explicitly stated as offered for service or communication. |
| `service_offering` | enum | An explicitly advertised offering. Values: `crematorium`, `chapel`, `reception_facilities`, `pre_planning`, `livestreaming`, `grief_resources`. |
| `service_area` | multi_text | Explicitly named geographic service areas. |
| `technology_signal` | enum | An explicitly named operational technology service. Version 1 emits only `online_arrangements` when clearly stated. |

The emitted version-1 set is seven keys. A later extractor version may add values without reinterpreting existing rows.

The following are deliberately excluded: revenue, market share, pricing estimates, staff counts, competitive rankings, inferred ownership, inferred service availability, and facts derived from absence.

## 3. Non-goals

- No canonical business-fact table or winner/current-value projection.
- No automatic entity, branch, website, or person mutation.
- No HTML-body persistence.
- No review queue in version 1.
- No inference from page absence, generic navigation, shared domains, logos, or third-party references.

## 4. Value representation

Each row stores one fact observation:

- `fact_key`: stable taxonomy identifier.
- `value_kind`: `enum`, `text`, `integer`, or `multi_text`.
- `raw_value`: exact extracted representation, trimmed but otherwise preserved.
- `normalized_value`: deterministic comparison/reporting representation.
- `enum_value`: represented in `normalized_value` for enum facts.

Normalization rules:

- enum values are lowercase ASCII taxonomy values;
- text values collapse internal whitespace and preserve meaningful spelling/case in `raw_value`;
- `founded_year` is a four-digit year from 1800 through the current extraction year, and is rejected when only an inferred date is available;
- languages and service areas are split only on explicit list boundaries, normalized with Unicode case-folding and whitespace collapse, deduplicated, and sorted for reporting;
- no normalization may convert an absent or negated statement into a positive fact.

## 5. Positive evidence and exclusions

Extraction is limited to visible HTML from eligible first-party pages. Positive evidence must be a nearby explicit phrase or structured label/value pair. The evidence snippet must contain the supporting text.

Relevant page kinds are `about`, `history`, `locations`, `contact`, `root`, and pages whose content is explicitly about services, facilities, planning, grief resources, or company information. Team/staff pages are not used unless they contain a clearly labelled business fact. Discovery also gives bounded priority and explicit Business-Fact eligibility to existing `other` pages whose persisted path or link metadata identifies supported patterns such as services, cremation, facilities, chapel, reception, ownership, planning, livestreaming, grief resources, or online arrangements. Generic `other` pages remain excluded; this does not broaden processing to every `other` page.

Excluded content includes `script`, `style`, `noscript`, navigation/footer/social blocks, obituaries, memorials, testimonials, customer reviews, vendor/supplier pages, marketing/SEO claims about another business, privacy/terms pages, and third-party links. Negated forms such as “we do not offer” never produce a positive row. Ambiguous or weakly contextual text is not emitted.

## 6. Observation lifecycle

Observations are append-only. The database does not update or delete a prior fact row during extraction.

The logical idempotence key is:

`website_page_id + content_hash + fact_key + normalized_value + raw_value + scope_entity_id`

An unchanged page/body and identical extracted fact returns the existing row. A changed content hash creates a new historical row. Conflicting values coexist as separate rows. No automatic winner, current value, or canonical fact is selected.

Old observations remain queryable. A read-only report may group rows by page/fact/scope and label multiple normalized values as `conflict`, repeated same values across snapshots as `repeated`, and one value as `observed`; it must never call these identity or truth determinations.

## 7. Provenance model

Every row stores:

- `website_page_id`, `website_id`, and `entity_id`;
- source URL snapshot and page-kind snapshot;
- fact key and value kind;
- raw and normalized value;
- confidence, extraction method, and extractor version;
- evidence snippet;
- body content hash;
- observed/created timestamp;
- scope (`explicit`, `inherited_from_website`, or `ambiguous`) and optional `scope_entity_id`.

The ingestion service validates that page, website, and entity IDs currently agree. The IDs and URL/page-kind snapshots are retained together so reports remain understandable even if related metadata later changes. `scope_entity_id` is only populated for explicit scope and must reference an existing entity.

## 8. Content-hash and snapshot semantics

The extractor receives body bytes and computes SHA-256 exactly as the Phase 8 observation extractor does. The hash identifies the page snapshot; timestamps do not participate in uniqueness. Re-fetching unchanged content is idempotent. Any body change is eligible for a new observation, even if the normalized fact is unchanged, preserving historical evidence.

## 9. Conflict semantics

Rows with different normalized values for the same page, fact key, and scope are retained. Reports expose `conflict` only when multiple values are present in the selected observation population. Conflicts are not resolved automatically and do not modify canonical entities or branches. Low-confidence rows remain visible with their confidence; no threshold silently deletes them.

## 10. Branch and shared-domain semantics

Scope is explicit only when the page text, heading, URL/path, address/location context, or existing page/entity relationship provides a direct branch reference. A branch page may produce an explicit branch-scoped fact when that evidence is present. A root or shared-domain page defaults to `inherited_from_website` only for organization-level facts and is `ambiguous` for branch-specific claims. Shared-domain membership alone never assigns a branch. Ambiguous scope is retained and reported, not promoted.

## 11. Extraction input boundary

The offline extraction service accepts page metadata (`website_page_id`, `website_id`, `entity_id`, URL, page kind), `body: bytes`, `content_type`, `status_code`, and optional final/source URL. It returns typed fact candidates and never performs network I/O. The bounded re-fetch pipeline may call it after `probe_http`; fixture tests call it directly. Raw bodies are not persisted by this phase.

## 11a. Explicit production processing

Business-fact processing is an explicit post-crawl operation exposed as
`business-facts extract`. It selects persisted eligible `website_pages` using
`--website-id` and/or `--page-id`, then performs bounded re-fetching through
the repository's existing `probe_http()` mechanism. The current response body,
content type, status code, and final/requested URL are passed to the existing
extractor; raw response bodies are not persisted.

The command processes pages independently and reports selected, attempted,
succeeded, and failed pages together with extracted, inserted, and unchanged
fact counts. A retrieval failure for one page does not prevent unrelated
selected pages from being attempted. Database and extractor integrity errors
remain command failures.

Crawler completion alone does not imply business-fact extraction. The crawler
persists page metadata and does not invoke the business-fact extractor. The
main offline pipeline also does not run this stage. `business-facts list`,
`business-facts summary`, and `business-facts export` remain read-only views of
already persisted observations and perform no network retrieval.

Repeated extraction delegates idempotence and historical snapshot behavior to
`store_business_facts()`: identical content and facts remain unchanged, while
changed content hashes create historical observations. No raw HTML archive is
introduced.

Business-Fact re-fetches also record page-level network truth in the nullable
`website_pages.last_*` fetch-state fields. This state is independent of fact
extraction and persistence: `last_fetched_at` is not extraction time,
`last_success_at` survives later failures, `last_failure_at` survives later
successes, and `last_content_hash` is the hash of the latest successfully
retrieved body, even when extraction emits zero facts. Response bodies are not
stored. The fetch-state fields currently provide observability only and do not
create a cache or freshness-based request-skipping policy. Website-level
`website_checks` and batch-verification retry state remain separate.

People extraction uses persisted page metadata only to select eligible people
page kinds and establish deterministic ordering. Historical discovery status,
content type, and identity metadata do not permanently suppress an eligible
people page: the current bounded `probe_http()` response is authoritative for
whether extraction proceeds. Current non-success, non-HTML, soft-404, and
parked responses remain rejected. Crawling and extraction remain separate
explicit operations; neither people extraction nor Business-Fact extraction is
automatically invoked when crawling completes.

## 12. Storage design

Migration `0017_create_business_fact_observations.sql` adds `business_fact_observations`. It uses a restrictive page FK and stores website/entity/page snapshots described above. The unique key is the logical idempotence key. There is no mutable `current` column and no canonical business-fact table.

## 13. Proposed migration

The migration adds the observation table and indexes on page, website, entity, fact key, normalized value, content hash, and scope. It adds CHECK constraints for fact keys, value kinds, confidence, scope, and nonblank provenance. No existing tables are altered.

## 14. Read-only CLI/reporting

Version 1 adds:

- `business-facts list` with optional `--entity-id`, `--website-id`, `--page-id`, and `--fact-key`;
- `business-facts summary` with the same filters;
- `business-facts export --output DIRECTORY` producing deterministic `business_facts.csv` and `business_fact_summary.csv`.

All commands are read-only and sorted by entity, website, page, fact key, normalized value, content hash, and row ID. Summary states are `observed`, `repeated`, `conflict`, or `ambiguous_scope` and are descriptive only.

## 15. Index/query strategy

Listing uses indexed provenance filters. Summary/export loads observations with one bounded query, groups in memory by `(entity_id, website_id, website_page_id, fact_key, scope_entity_id)`, and sorts keys before serialization. No per-row database query is required.

## 16. Required tests

Tests must cover every emitted fact key, positive and negative extraction, excluded content, raw/normalized values, confidence and provenance, branch/shared-domain scope, duplicate idempotence, changed-content snapshots, conflicts, deterministic list/JSON/CSV, migration constraints/idempotence, and unchanged non-Phase-10 tables. All inputs are fixture bodies and temporary SQLite databases.

## 17. Safety invariants

Business-fact extraction never changes entities, parent relationships, websites, website review state, pages, people, observations, dispositions, remediation tasks, source records, or canonical values. It never crawls, calls social media, writes production, or treats a fact as identity evidence without an explicit later design.

## 18. Explicitly deferred work

Review queues, canonical/current projections, fact confidence recalibration, automated conflict resolution, refresh orchestration, business-intelligence scoring, raw-body archives, and additional taxonomy values are deferred. Taxonomy changes require a new extractor/taxonomy version and must not reinterpret historical rows.
