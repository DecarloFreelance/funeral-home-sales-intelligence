# Data Layout

The repository keeps reusable research inputs separate from private client data
and generated output.

- `seeds/`: reviewed, reusable source records that may be committed
- `private/`: client-specific inputs; ignored by Git
- `generated/`: crawls, scoring results, outreach drafts, and reports; ignored
  by Git
- `discovery_sources/`: generated provider exports; ignored except `.gitkeep`

Do not place credentials, private correspondence, purchased lists, or client
exports in `seeds/`. Generated output may contain public business contact data,
but it is still kept out of version control to prevent accidental disclosure and
unbounded repository growth.

The historical v34 reference campaign is preserved under
`legacy/reference_campaign/` and is not used by current default workflows.
