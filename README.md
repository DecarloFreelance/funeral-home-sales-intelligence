# Funeral Home Sales Intelligence

AI-powered platform for discovering, auditing, scoring, and prioritizing funeral home sales opportunities.

## Current Capabilities

- Website crawling and analysis
- Digital conversion gap detection
- Lead scoring
- Revenue opportunity scoring
- Executive sales briefs
- Outreach package generation
- CRM-ready exports
- Persistent CRM lead state and engagement history
- Prioritized CRM action queue with start/completion tracking

## Current Development Status

The architecture-consolidation work identified in the Phase 8 audit is now
substantially implemented:

- Unified `LeadIntelligence` records are the internal source of truth.
- Contact data is cleaned, validated, ranked, and assigned confidence scores.
- Outreach priority and preferred contact method feed the CRM state directly.
- Active CRM actions are deduplicated and tracked through their lifecycle.
- Focused CRM workflow regression tests are available under `tests/`.

Run the automated checks with:

```bash
python -m unittest discover -v
```

Automated discovery, public contact extraction, platform-candidate ranking, and
reviewable outreach generation, the operator interface, progressive local
verification, and an EspoCRM synchronization boundary are implemented.

Start the local operator interface with:

```bash
flask --app operator_ui.app run --host 127.0.0.1
```

The interface reads existing generated datasets and exposes confirmed, CSRF-
protected operator actions. CSV and JSON discovery sources can be normalized and
previewed without changing data, then explicitly confirmed to atomically replace
the generated crawl queue. Controlled crawl batches can be started in replace or
resume/append mode, with bounded settings and local domain-level progress.
Research-domain replacements can be previewed and confirmed with required
evidence, rationale, and medium/high confidence. Confirmation updates the
reviewed ledger and rebuilds retry, summary, and remaining-research outputs.
Generated platform outreach drafts can be approved only while their recipient
remains a usable candidate email. Approval writes a private `APPROVED_UNSENT`
audit record and never sends or edits the message.

## Data Safety and Layout

Reusable seeds, private client inputs, and generated output are deliberately
separated:

- `data/seeds/` contains reviewed reusable inputs that may be versioned.
- `data/private/` contains client-specific inputs and is ignored by Git.
- `data/generated/` contains crawls, reports, scores, and outreach drafts and is
  ignored by Git.
- `legacy/reference_campaign/` preserves historical reference data but is not
  used by current workflows.

See `data/README.md` before adding a new source or client campaign. Never commit
credentials, purchased contact lists, or private client correspondence.

## Discovery Ingestion

Add controlled reusable leads to `data/seeds/manual_leads.csv`, then generate the normalized,
deduplicated crawler queue:

```bash
python manual_import.py
```

This writes the generated `data/crawl_queue.json`. Each record includes a
canonical domain, source and location metadata, and priority contact/about/team
URLs. An external crawler can process that queue and write crawled page records
to `data/generated/campaign/leads.json`, the default input to `lead_scoring.py`.

The included controlled crawler bridges the queue to analysis without replacing
the existing crawl dataset:

```bash
python website_crawler.py
python lead_scoring.py \
  --input data/discovered_leads.json \
  --output data/discovered_results.json
```

`website_crawler.py` visits each homepage and its same-domain priority contact,
about, team, staff, director, people, and location pages. Its default output is
separate from the historical reference campaign; pass an explicit `--output` only when replacing
or promoting a crawl intentionally. Use `--limit`, `--max-pages`,
`--max-attempts`, `--timeout`, and `--delay` for controlled pilots. The completion report lists domains where
no pages could be retrieved. Long crawls can be resumed in batches with
`--offset`, `--limit`, and `--append`; appended records are deduplicated by URL.
Each run also writes a structured `*_report.json` with URL-level successes,
HTTP/request failures, redirects, and non-HTML outcomes.

Build the follow-up research queue after crawling:

```bash
python build_research_queue.py
```

`data/research_queue.json` contains unresolved domains with their company and
branch records, source provenance, observed failure details, and a recommended
research action. Historical crawl output can seed the queue even when it
predates structured attempt reporting.

Apply reviewed replacement domains and reduce the queue after a crawl:

```bash
python apply_domain_resolutions.py
```

Reviewed mappings live in `data/seeds/domain_resolutions.json`. The command writes a
retry queue and resolution summary, then atomically replaces the research queue
with only unresolved domains and replacement sites that still could not be
retrieved.

Multiple search, maps, association, and directory exports can be merged before
crawling:

```bash
python discovery_import.py \
  --source manual=data/seeds/manual_leads.csv \
  --source maps=data/discovery_sources/maps.csv \
  --source search=data/discovery_sources/search.json \
  --source association=data/discovery_sources/association.csv
```

Sources may be CSV or JSON. JSON can contain a top-level list or a list under
`results`, `businesses`, `items`, `records`, or `data`. Common column aliases
such as `business_name`, `name`, `url`, `telephone`, `locality`, `state`, and
`listing_url` are normalized automatically. Maps and directory `url` fields are
treated as provider provenance unless a separate business website is present.
Each queue record retains all contributing source types and listing URLs.

### Live AFSA directory source

The first live connector reads the public Alberta Funeral Service Association
provider directory and exports its published business listings:

```bash
python afsa_discovery.py
python discovery_import.py \
  --source manual=data/seeds/manual_leads.csv \
  --source association=data/discovery_sources/afsa.json
```

The connector discovers the association's alphabetic member pages from the
directory index, waits between requests, and extracts only public business
fields. Domain deduplication retains every branch under `locations`, allowing a
single website crawl while preserving multi-location company, address, phone,
email, and source details.

### Live CANA directory source

The Cremation Association of North America public member directory provides a
controlled second association source with Canadian and United States coverage:

```bash
python cana_discovery.py --country Canada --country "United States"
python discovery_import.py \
  --source association=data/discovery_sources/cana.json
```

The connector retains public business, location, phone, category, named contact,
website, and listing provenance fields. Records without a published business
website remain in the provider export but are not added to a website crawl queue.
By default, supplier and uncategorized member records are excluded; use
`--include-other-members` only for an explicitly broader research scope. Live
Canada/U.S. acquisition and controlled crawl evidence is documented in
`audit/CANA_LIVE_DISCOVERY_VALIDATION.md`.

## Contact Intelligence

The scoring pipeline extracts contact intelligence from crawled page text,
pre-parsed `metadata.jsonLd`, and JSON-LD embedded in HTML. Results retain the
legacy email and phone fields and also include a `contact_intelligence` object
containing:

- Business names and postal addresses from schema.org data
- Validated email addresses and North American phone numbers
- Per-address email validation evidence: normalized syntax, DNS/MX domain
  acceptance, business-domain alignment, role/free-provider classification,
  risk flags, and confidence
- Per-number phone evidence: libphonenumber E.164 normalization, possibility,
  validity, country/region, number type, placeholder risks, and explicit
  carrier/reachability verification state
- Role-matched owners, presidents, managers, and funeral directors
- Source URLs and extraction method for each identified person
- A 0–100 contact completeness score

Decision-maker extraction is intentionally conservative: a person's name must
appear with a supported role in structured data or on the same/adjacent text
line.

Optional external verification adapters are available as
`ZeroBounceEmailVerifier` and `TwilioPhoneVerifier`. They are never enabled
implicitly: callers must construct and pass a provider with credentials. Failed
checks are recorded as `CHECK_FAILED`; omitted checks retain `NOT_CHECKED` and
`UNKNOWN`. Twilio data packages may incur charges, and Canadian line-type lookup
may require provider approval.

The confidence states are deliberately progressive: `DISCOVERED`, `LOCAL_VALID`,
`DNS_VALID` or `METADATA_VALIDATED`, and finally `EXTERNALLY_VERIFIED` when an
explicit paid provider succeeds. DNS/MX evidence proves only that a mail domain
accepts mail; it does not prove that an individual mailbox exists. Phone
metadata does not prove that a line is active or identify its current carrier.

## EspoCRM Synchronization

The local SQLite CRM remains the auditable workflow source of truth. EspoCRM is
the first external target behind the `CRMBackend` boundary. Configure a
least-privilege EspoCRM API user with Account read/create/edit access, keep its
key outside the repository, and synchronize one lead or all leads:

```bash
export ESPOCRM_URL="https://crm.internal.example"
export ESPOCRM_API_KEY="..."
python espocrm_sync.py --domain example.ca
python espocrm_sync.py --all
```

The adapter authenticates with `X-Api-Key`, searches by canonical website before
creating, retains remote IDs locally for subsequent updates, uses bounded
retries, and records every success or failure without modifying local lead
state. A live self-hosted instance is optional for development; automated tests
use deterministic fake sessions and backends and never make API calls.

## Platform-Candidate Workflow

Platform candidates are potential buyers or partners for the reusable system;
they are never mixed with a client's funeral-home campaign leads.

```bash
python platform_candidate_import.py
python website_crawler.py \
  --input data/generated/platform/platform_candidate_queue.json \
  --output data/generated/platform/platform_candidate_crawl.json \
  --report-output data/generated/platform/platform_candidate_crawl_report.json
python rank_platform_candidates.py
python build_platform_outreach.py
```

The final copy/paste email file is
`data/generated/platform/platform_candidate_outreach.txt`. JSON and CSV outputs
are also generated for software integrations; individual `.eml` drafts are
written under `data/generated/platform/emails/`. Draft generation never sends
email.

## v34.20 Baseline

Completed:
- Funeral home website intelligence engine
- Opportunity scoring framework
- Example client reporting
- Outreach workflow generation

## Roadmap

v35:
- Automated business discovery (implemented for AFSA and file adapters)
- Contact enrichment (implemented for public site and directory data)
- Funeral director identification (implemented conservatively)
- Email validation (local syntax and DNS/MX evidence implemented; optional
  mailbox verification remains available through ZeroBounce)
- Phone verification (local metadata validation implemented; optional live
  Lookup remains available through Twilio)
- EspoCRM synchronization (implemented; additional backends can use the same
  boundary)
