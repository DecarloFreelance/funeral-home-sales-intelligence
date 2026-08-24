import argparse
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


def select_scale_sample(records, size):
    eligible = sorted(
        (item for item in records
         if item.get("pages", 0) > 0 and (item.get("quality_control") or {}).get("crm_sync_safe") is True),
        key=lambda item: (item.get("executive_priority_score", 0), item.get("domain", "")),
    )
    if not eligible or size < 1:
        return []
    if size >= len(eligible):
        return eligible
    indexes = {round(index * (len(eligible) - 1) / (size - 1)) for index in range(size)} if size > 1 else {len(eligible) // 2}
    return [eligible[index] for index in sorted(indexes)]


def main():
    parser = argparse.ArgumentParser(description="Run a credential-safe live EspoCRM validation sample.")
    parser.add_argument("--results", type=Path)
    parser.add_argument("--sample-size", type=int, default=3)
    args = parser.parse_args()
    site_url = os.environ.get("ESPOCRM_URL")
    api_key = os.environ.get("ESPOCRM_API_KEY")
    if not site_url or not api_key:
        raise SystemExit("ESPOCRM_URL and ESPOCRM_API_KEY must be set")

    original_db = database.DB
    with tempfile.TemporaryDirectory(prefix="fhsi-espo-live-") as temp_dir:
        database.DB = Path(temp_dir) / "crm.sqlite"
        try:
            initialize()
            if args.results:
                records = json.loads(args.results.read_text(encoding="utf-8"))
                selected = select_scale_sample(records, args.sample_size)
                if not selected:
                    raise RuntimeError("No website-processed CRM-safe records are available for sampling")
            else:
                selected = [{
                    "domain": VALIDATION_DOMAIN, "business_profile": {"company": "EspoCRM Adapter Validation"},
                    "executive_priority_score": 100,
                }]
            backend = EspoCRMBackend(site_url, api_key)
            synchronized = []
            for record in selected:
                domain = record["domain"]
                upsert_lead({
                    "domain": domain,
                    "company_name": (record.get("business_profile") or {}).get("company") or domain,
                    "pipeline_stage": "NEW",
                    "crm_status": "TEST",
                    "priority_score": record.get("executive_priority_score", 0),
                    "priority_level": "B1 - Nurture",
                    "contact_method": "research",
                    "primary_email": "",
                    "primary_phone": "",
                    "next_action": "Validate EspoCRM adapter",
                    "follow_up_date": "",
                    "crm_sync_safe": True,
                    "outreach_ready": True,
                })
                first_id = sync_lead(domain, backend)
                second_id = sync_lead(domain, backend)
                if first_id != second_id:
                    raise RuntimeError("EspoCRM sync created inconsistent remote IDs")
                remote = backend.get_account(first_id)
                if remote.get("website") != f"https://{domain}":
                    raise RuntimeError("EspoCRM Account field mapping did not round-trip")
                synchronized.append({"domain": domain, "remote_id": first_id})
            with sqlite3.connect(database.DB) as conn:
                events = conn.execute(
                    "SELECT status FROM external_crm_sync_events ORDER BY id"
                ).fetchall()
            if events != [("SUCCEEDED",)] * (2 * len(selected)):
                raise RuntimeError("Local EspoCRM audit trail is incomplete")
            print(json.dumps({
                "status": "PASSED",
                "accounts": synchronized,
                "sync_events": len(events),
            }, indent=2))
        finally:
            database.DB = original_db


if __name__ == "__main__":
    main()
