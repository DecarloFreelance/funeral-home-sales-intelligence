# Import Ontario BAO Register Records

The Ontario Bereavement Authority (BAO) public register is an authoritative
source for licensed Ontario operators. It is an interactive public register,
not a validated bulk-download source in this repository.

The registered source is:

`Ontario Bereavement Authority Public Register`

Source URL: `https://portal.thebao.ca/public-register/`

## Acquisition boundary

This runbook does not automate searches, submit requests, bypass access
controls, or crawl the register. A reviewer must obtain an authorized local
export or manually prepared source file and record its retrieval date,
provenance, terms, and SHA-256 checksum.

Do not infer a website URL from the register's page URL. Preserve any explicit
website field only when the supplied record labels it as such. Contact details,
licence status, ownership, and location are source observations; they do not
approve a website, assign a primary website, or resolve entity identity.

## Local import

Use a temporary or development database. Never target
`database/sqlite/funeral_homes.sqlite3`.

```bash
DB_PATH=/tmp/cfi-ontario-bao.sqlite3
SOURCE_FILE=/tmp/ontario-bao-register.json

DATABASE_PATH="$DB_PATH" .venv/bin/python -m canada_funeral_intel db init
DATABASE_PATH="$DB_PATH" .venv/bin/python -m canada_funeral_intel sources seed
DATABASE_PATH="$DB_PATH" .venv/bin/python -m canada_funeral_intel import \
  --source "Ontario Bereavement Authority Public Register" \
  --format json \
  "$SOURCE_FILE"
DATABASE_PATH="$DB_PATH" .venv/bin/python -m canada_funeral_intel normalize \
  --source "Ontario Bereavement Authority Public Register"
```

The importer preserves the original payload and checksum. Normalized business
names, addresses, phones, emails, URLs, domains, and explicit website aliases
use the shared normalization rules. Unknown regulator fields remain in the raw
payload until a source-specific contract defines them.

Before entity materialization, inspect licence categories, duplicate locations,
source identifiers, and explicit website-field coverage. A missing register
record is not evidence that an operator closed.

Do not run website verification, page discovery, people extraction, or business
fact extraction as part of source import validation.
