# Canada Funeral Intelligence

A data pipeline for building and maintaining a unified database of Canadian
funeral homes with verified websites, contact information, staff profiles,
source provenance, and confidence scores.

## Planned pipeline

1. Import public and appropriately licensed source datasets.
2. Normalize names, addresses, telephone numbers, domains, and locations.
3. Deduplicate records while preserving source provenance.
4. Verify websites, redirects, TLS, status codes, and business identity.
5. Discover contact, about, team, staff, and location pages.
6. Extract public staff names, roles, emails, phones, and evidence URLs.
7. Assign verification, completeness, and confidence scores.
8. Export clean SQLite, CSV, and JSON datasets.

## Public directory

The repository also contains a curated static directory for GitHub Pages under
`site/`. Build its public-safe snapshot with:

```bash
python scripts/build_public_directory.py
```

The exporter opens SQLite read-only and excludes raw payloads, internal review
notes, unresolved people, contact points, and business-fact evidence. See
[`docs/PUBLIC_DIRECTORY.md`](docs/PUBLIC_DIRECTORY.md) for the public schema
and deployment workflow.
