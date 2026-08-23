import json
import os
import sqlite3
import tempfile
from pathlib import Path

from crm import database
from crm.database import initialize, upsert_lead
from crm.espocrm import EspoCRMBackend
from crm.sync import sync_lead


VALIDATION_DOMAIN = "espocrm-adapter-validation.invalid"


def main():
    site_url = os.environ.get("ESPOCRM_URL")
    api_key = os.environ.get("ESPOCRM_API_KEY")
    if not site_url or not api_key:
        raise SystemExit("ESPOCRM_URL and ESPOCRM_API_KEY must be set")

    original_db = database.DB
    with tempfile.TemporaryDirectory(prefix="fhsi-espo-live-") as temp_dir:
        database.DB = Path(temp_dir) / "crm.sqlite"
        try:
            initialize()
            upsert_lead({
                "domain": VALIDATION_DOMAIN,
                "company_name": "EspoCRM Adapter Validation",
                "pipeline_stage": "NEW",
                "crm_status": "TEST",
                "priority_score": 100,
                "priority_level": "B1 - Nurture",
                "contact_method": "research",
                "primary_email": "",
                "primary_phone": "",
                "next_action": "Validate EspoCRM adapter",
                "follow_up_date": "",
            })
            backend = EspoCRMBackend(site_url, api_key)
            first_id = sync_lead(VALIDATION_DOMAIN, backend)
            second_id = sync_lead(VALIDATION_DOMAIN, backend)
            if first_id != second_id:
                raise RuntimeError("EspoCRM sync created inconsistent remote IDs")
            remote = backend.get_account(first_id)
            if remote.get("website") != f"https://{VALIDATION_DOMAIN}":
                raise RuntimeError("EspoCRM Account field mapping did not round-trip")
            with sqlite3.connect(database.DB) as conn:
                events = conn.execute(
                    "SELECT status FROM external_crm_sync_events ORDER BY id"
                ).fetchall()
            if events != [("SUCCEEDED",), ("SUCCEEDED",)]:
                raise RuntimeError("Local EspoCRM audit trail is incomplete")
            print(json.dumps({
                "status": "PASSED",
                "domain": VALIDATION_DOMAIN,
                "remote_id": first_id,
                "sync_events": 2,
            }, indent=2))
        finally:
            database.DB = original_db


if __name__ == "__main__":
    main()
