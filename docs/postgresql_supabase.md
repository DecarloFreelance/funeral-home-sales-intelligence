# PostgreSQL / Supabase Persistence

PostgreSQL is a reversible persistence target for canonical research snapshots.
The enrichment pipeline remains the authority for research behavior, and
`data/crm.sqlite` remains the authority for CRM workflow and outreach state.
The importer never sends outreach and does not write to SQLite or EspoCRM.

## Security and connection

The database layer reads `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, and
`PGSSLMODE`. TLS is mandatory: only `require`, `verify-ca`, or `verify-full` is
accepted. Authentication is delegated to libpq, so `~/.pgpass` or a runtime
`PGPASSWORD` may be used without putting a password in the repository, argv, or
a connection URL. Through a transaction/session pooler, `pg_stat_ssl` may
describe the pooler's backend connection rather than the client leg; the CLI
therefore reports both mandatory client `sslmode` enforcement and any available
server-side observation separately.

For this workstation, load the untracked operator configuration before running
commands:

```bash
set -a
. ~/.config/supabase/decarlo.env
set +a
python database_cli.py connect
```

Do not source or copy `.pgpass` into this repository.

## Operations

```bash
python database_cli.py status
python database_cli.py migrate
python database_cli.py import --dry-run
python database_cli.py import --apply
python database_cli.py validate
python database_cli.py coverage --dry-run
python database_cli.py coverage --apply
```

Use `--directory PATH` and `--crm PATH` to validate a different immutable
canonical snapshot or SQLite backup. Dry-run requires no database connection.
Imports use temporary client-side CSV files, one PostgreSQL transaction, stable
content-derived IDs, foreign keys, and conflict-safe upserts. Failed imports
roll back as a unit. Existing source files are never deleted or modified.

## Schema boundary

All objects live in the dedicated `fhsi` schema. Versioned migrations are in
`persistence/sql/`, and applied versions are recorded in
`fhsi.schema_migrations`.

- `organizations`: frequently queried canonical branch/business fields.
- `source_records`: lossless canonical source payloads and hashes.
- `organization_websites`: branch-to-site mappings; domains are indexed but not
  unique because corporate and hosted domains are legitimately shared.
- `evidence_sources`: reusable URL/file/hash/excerpt provenance.
- `contacts`: branch-safe normalized emails and phones linked to evidence.
- `people`: staff and conservative decision-maker flags linked to evidence.
- `research_facts`, `manual_review_findings`, and
  `organization_resolutions`: normalized persistence contracts for existing
  evidence/review/resolution concepts; import is deferred until their canonical
  generated artifacts are selected rather than guessing across historical runs.
- `crm_lead_snapshots`: read-only snapshots of local lead state. No CRM event,
  action-queue, pilot, approval, draft, or outreach event is imported.
- `crawl_runs`, `crawl_targets`, and `crawl_pages`: reviewed crawl coverage,
  attempts, searchable extracted text, structured metadata, and content hashes.
  Raw HTML remains in the local generated evidence corpus.

Shared domains are intentionally allowed. Duplicate handling occurs through
stable source IDs and explicit organization-resolution records, never by
silently collapsing branches.
