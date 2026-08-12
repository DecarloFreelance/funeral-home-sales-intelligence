# Import Manually Researched Website Evidence

This is an offline intake path for URLs researched by a reviewer. It attaches
each row to an existing active `entity_id`; it never creates an entity, approves
a website, selects a primary site, or performs DNS/HTTP requests.

## CSV format

Required columns:

```csv
entity_id,website_url,source_url,note
123,https://example.ca/,https://directory.example/123,"Name and address match"
```

`source_url` and `note` are optional but recommended. They are retained in the
raw source-record payload for audit. The original `website_url` is preserved
alongside its normalized value.

## Dry run

First generate a deterministic template for active entities without a current
non-rejected candidate:

```bash
DATABASE_PATH=/tmp/cfi.sqlite3 \
  .venv/bin/python -m canada_funeral_intel website manual-template \
  --output /tmp/manual-website-evidence.csv \
  --limit 50
```

Fill only `website_url`, `source_url`, and `note`; do not change `entity_id`.

```bash
DATABASE_PATH=/tmp/cfi.sqlite3 \
  .venv/bin/python -m canada_funeral_intel website import-manual \
  /tmp/manual-website-evidence.csv \
  --dry-run
```

Dry-run validates active entity IDs and URL normalization without writing source
records, normalized values, candidates, or review rows.

## Import

```bash
DATABASE_PATH=/tmp/cfi.sqlite3 \
  .venv/bin/python -m canada_funeral_intel website import-manual \
  /tmp/manual-website-evidence.csv
```

The command creates an idempotent manual source record and normalized
`manual_website_url` signal for each row, then reuses the standard offline
candidate generator. Candidates are placed in the existing website review
workflow. Repeating the same file does not duplicate source records, candidates,
or evidence.

Use a temporary or development database. Never target
`database/sqlite/funeral_homes.sqlite3` without an explicitly authorized
production operation.
