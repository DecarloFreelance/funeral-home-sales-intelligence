# Data Migration Review

Date: 2026-08-22
Status: Validated

## Scope

Reviewed the uncommitted migration from root-level campaign data into the
repository's reusable seed, ignored generated/private, and historical reference
areas.

## Historical Data Preservation

The versions of the deleted root files in `HEAD` were compared byte-for-byte
with their archived replacements:

- `data/leads.json` equals `legacy/reference_campaign/data/leads.json`.
- `data/outreach_contacts.csv` equals
  `legacy/reference_campaign/data/outreach_contacts.csv`.
- `data/todd_outreach_campaign.csv` equals
  `legacy/reference_campaign/data/outreach_campaign.csv`.

The root `todd_outreach_export.py` is preserved under
`legacy/reference_campaign/todd_outreach_export.py` with only its input and
output paths redirected to the historical directory. Its historical source
`results.json` was not tracked in `HEAD`, so the script is retained as a
reference implementation rather than represented as a self-contained runnable
campaign.

## Ignore Boundary Validation

`git check-ignore -v` confirmed that these runtime/private examples are ignored:

- `data/generated/example.json`
- `data/private/client.json`
- `data/crm.sqlite`
- `data/crawl_queue.json`
- `data/discovery_sources/sample.json`

It also confirmed that the following are not ignored and can be versioned:

- `data/seeds/manual_leads.csv`
- `data/generated/.gitkeep`
- `data/private/.gitkeep`

Generated provider exports are ignored while
`data/discovery_sources/.gitkeep` remains versionable.

## Conclusion

The deletions are intentional relocations, not data loss. The active workflows
now write generated output outside the historical snapshot. Private inputs and
runtime CRM state are excluded from version control, and reviewed reusable seeds
remain eligible for versioning.

No credentials or secrets were found in the reviewed migration paths.
