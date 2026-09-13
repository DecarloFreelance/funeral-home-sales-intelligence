# Local EspoCRM test environment

Archived 2026-09-12: this integration (this stack, `crm_espocrm.py`,
`crm_sync.py`, `espocrm_sync.py`, and `validate_espocrm_live.py`, all in this
`legacy/espocrm_integration/` folder) showed no evidence of recent use and
nothing else in the live pipeline depends on it, so it was moved out of the
way. It's otherwise unchanged and should still work if revived.

This stack follows EspoCRM's official Docker layout with pinned application and
database versions. It binds the web service to localhost only and keeps
credentials in the ignored `.env` file.

1. Copy `.env.example` to `.env` and replace every password.
2. Start the stack with `docker compose --env-file .env up -d` from this folder.
3. Open `http://localhost:8080`, sign in as the configured administrator, and
   create a Role with Account read/create/edit permissions only. Set Account
   delete and stream access and all global assignment, user, message, export,
   mass-update, and audit permissions to `no`.
4. Create an API User using API Key authentication and assign that Role.
5. Export `ESPOCRM_URL=http://localhost:8080` and the generated key as
   `ESPOCRM_API_KEY`.
6. From the repository root run `python legacy/espocrm_integration/validate_espocrm_live.py`.

The validation creates or updates only `espocrm-adapter-validation.invalid`,
uses a temporary local SQLite database, performs two syncs to prove remote-ID
reuse, and reads the resulting Account back through the real API. It does not
print or persist the API key.

Inspect with `docker compose --env-file .env ps` and stop while preserving data
with `docker compose --env-file .env down`.
