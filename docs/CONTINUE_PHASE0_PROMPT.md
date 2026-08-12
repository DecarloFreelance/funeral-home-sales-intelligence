You are continuing development of the Canada Funeral Intelligence Platform.

Repository:

~/canada_funeral_intel

Authoritative plan:

docs/PROJECT_PLAN.md

Inspect the repository and read the project plan before modifying anything.

Implement only Phase 0 — Foundation. Do not implement source downloads, source imports, normalization, entity resolution, website discovery, website verification, crawling, staff extraction, scoring, reporting, or exports.

## Required work

1. Add typed configuration loaded from environment variables.
2. Validate integer, float, path, concurrency, timeout, delay, and log-level values with clear errors.
3. Support:
   - DATABASE_PATH
   - LOG_LEVEL
   - HTTP_USER_AGENT
   - HTTP_TIMEOUT_SECONDS
   - REQUEST_DELAY_SECONDS
   - MAX_CONCURRENCY
4. Add structured logging using the Python standard library.
5. Add SQLite connection helpers.
6. Enable SQLite foreign keys on every connection.
7. Add explicit transaction handling with rollback on failure.
8. Add a deterministic SQL migration system using files under `database/migrations`.
9. Record applied migrations in `schema_migrations`.
10. Make repeated migration runs safe.
11. Add lightweight typed models using dataclasses and enums where appropriate.
12. Add the initial schema for:
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
13. Preserve original source payloads and provenance.
14. Support multiple source records per funeral home.
15. Support multiple websites and website-check history.
16. Support people and evidence URLs.
17. Add `src/canada_funeral_intel/__main__.py`.
18. Implement these commands:
    - `python -m canada_funeral_intel --help`
    - `python -m canada_funeral_intel config show`
    - `python -m canada_funeral_intel db init`
    - `python -m canada_funeral_intel db migrate`
    - `python -m canada_funeral_intel db status`
19. Ensure `config show` is designed to redact secret fields introduced later.
20. Add useful exit codes and error messages.
21. Update README and architecture documentation.
22. Add unit and integration tests.

## Constraints

- Python 3.11 or newer.
- Preserve the existing repository structure.
- Use SQLite through the standard-library `sqlite3` module.
- Do not add an ORM.
- Do not add a dotenv dependency.
- Use standard-library modules where practical.
- Do not silently swallow errors.
- Tests must use temporary databases.
- Tests must never modify the configured production database.
- Schema changes must be implemented through migration files.
- Timestamps should be UTC and unambiguous.
- Do not implement Phase 1 or later.

## Tests required

Cover at least:

- default configuration
- environment overrides
- invalid integer and float values
- invalid ranges
- database connection creation
- foreign-key enforcement
- transaction commit
- transaction rollback
- clean database initialization
- deterministic migration ordering
- repeated migration execution
- migration status
- insertion of a minimal source dataset
- insertion of a source record
- creation of a funeral-home location
- source provenance relationships
- website and website-check history
- person and person-evidence relationships
- CLI help
- `config show`
- `db init`
- `db migrate`
- `db status`

## Validation

Run and fix all failures:

```bash
python -m compileall -q src tests
python -m pytest -q
python -m canada_funeral_intel --help
python -m canada_funeral_intel config show
python -m canada_funeral_intel db init
python -m canada_funeral_intel db migrate
python -m canada_funeral_intel db status
```

At completion, report:

1. Files created or changed.
2. Migration and schema design.
3. Test results.
4. CLI demonstration results.
5. Architectural decisions affecting later phases.
6. Exact recommended scope for Phase 1.

Do not implement Phase 1.
