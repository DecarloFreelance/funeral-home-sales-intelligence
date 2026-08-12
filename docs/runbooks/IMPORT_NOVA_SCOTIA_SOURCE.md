# Import Nova Scotia Licensed Funeral Source

This runbook imports a locally obtained copy of the Nova Scotia open dataset.
It does not download the source, migrate production, verify websites, or assign
entities automatically.

Source: `Nova Scotia Licensed Funeral Homes and Related Sellers`

The dataset includes multiple licensed categories, including funeral homes,
crematoriums, cemeteries, and funeral sellers. Preserve the category in the
raw payload and filter it explicitly during downstream materialization. Do not
interpret a missing row as closure.

## Preconditions

Use a temporary or development database. The production path
`database/sqlite/funeral_homes.sqlite3` is not an allowed target for this
workflow.

The current CSV schema is:

`License Type`, `Licensee Name`, `PRE ARRANGED FUNERAL PLAN SALES `, `Address`,
`City`, `Province`, `Postal Code`, and `Location Geocode`.

The current file has no stable external-ID column and no website column. Omit
`--external-id-field` for this release; import idempotence uses the source
dataset and payload checksum. A future source revision with a stable identifier
should use that identifier after inspection.

The local file must be obtained through an authorized process and should be
stored outside the repository. Record its SHA-256 checksum and retrieval date
before import.

## Import

```bash
DB_PATH=/tmp/cfi-ns.sqlite3
SOURCE_FILE=/tmp/ns-licensed-funeral-services.csv

DATABASE_PATH="$DB_PATH" .venv/bin/python -m canada_funeral_intel db init
DATABASE_PATH="$DB_PATH" .venv/bin/python -m canada_funeral_intel sources seed
DATABASE_PATH="$DB_PATH" .venv/bin/python -m canada_funeral_intel import \
  --source "Nova Scotia Licensed Funeral Homes and Related Sellers" \
  --format csv \
  "$SOURCE_FILE"
DATABASE_PATH="$DB_PATH" .venv/bin/python -m canada_funeral_intel normalize \
  --source "Nova Scotia Licensed Funeral Homes and Related Sellers"
```

Unknown fields remain in `source_records.raw_payload`. The current source
normalizes `Licensee Name`, `License Type`, address, city, province, and postal
code. Recognized `website`, `website_url`, `url`, and explicit website aliases
become normalized website signals when a future source revision provides them.

## Verification checks

```bash
DATABASE_PATH="$DB_PATH" .venv/bin/python -m canada_funeral_intel sources list
DATABASE_PATH="$DB_PATH" .venv/bin/python -m canada_funeral_intel website populate-candidates \
  --source-dataset-id <N> --entity-limit 25 --candidate-limit 1 --dry-run
```

Before materialization, inspect category counts, malformed records, duplicate
identifiers, and website-signal counts. Candidate population is offline and
does not approve websites or assign primary sites.

Do not run `website batch-verify` as part of source import validation.
