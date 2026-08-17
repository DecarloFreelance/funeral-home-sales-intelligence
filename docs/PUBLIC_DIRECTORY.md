# Public Directory

The repository includes a static, searchable directory under `site/` for
GitHub Pages deployment.

## Build the public snapshot

The exporter opens SQLite read-only and writes only the curated research JSON
file. It excludes raw source payloads, internal review notes, unresolved
people, person contact points, business-fact evidence, and fetch diagnostics.

```bash
python scripts/build_public_directory.py \
  --database database/sqlite/funeral_homes.sqlite3 \
  --output site/data/directory.json
```

The default paths are the same as the command above. Review the generated
snapshot before publishing it.

## Public fields

Each record contains only:

- entity ID and type;
- canonical name when available;
- normalized city and province when available;
- source dataset names;
- one best-ranked website URL and its current candidate status.
- reviewed business facts such as services, ownership, founded year, and
  service area;
- people with accepted evidence, limited to name, role, and branch context.

The website is a preliminary research directory. A record is not a claim that
the business is currently operating, that a website is verified, or that two
source records represent the same legal organization.

## GitHub Pages

The workflow at `.github/workflows/pages.yml` deploys the committed `site/`
directory as a static GitHub Pages site. It does not access SQLite, perform
network retrieval, or generate data in CI. Refresh the JSON snapshot locally,
review the public fields, and commit the approved snapshot before deployment.

## Access control

A browser-side password prompt is not security: static files remain
downloadable. GitHub's supported private Pages access control requires GitHub
Enterprise Cloud, an organization-owned private or internal repository, and
repository read access for each visitor. Otherwise, place the site behind an
authenticated proxy such as Cloudflare Access or deploy it to an application
host with server-side authentication.
