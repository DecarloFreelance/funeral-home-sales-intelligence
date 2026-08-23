import argparse
import os

from crm.database import connect
from crm.espocrm import EspoCRMBackend
from crm.sync import sync_lead


def main():
    parser = argparse.ArgumentParser(
        description="Synchronize local CRM leads to an approved EspoCRM instance."
    )
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--domain", help="Synchronize one local lead domain")
    selection.add_argument("--all", action="store_true", help="Synchronize all local leads")
    parser.add_argument("--db", help="Override the local SQLite CRM path")
    args = parser.parse_args()

    site_url = os.environ.get("ESPOCRM_URL")
    api_key = os.environ.get("ESPOCRM_API_KEY")
    if not site_url or not api_key:
        parser.error("ESPOCRM_URL and ESPOCRM_API_KEY must be set")

    if args.all:
        with connect(args.db) as conn:
            domains = [row[0] for row in conn.execute("SELECT domain FROM leads ORDER BY domain")]
    else:
        domains = [args.domain]

    backend = EspoCRMBackend(site_url, api_key)
    for domain in domains:
        remote_id = sync_lead(domain, backend, args.db)
        print(f"{domain}: {remote_id}")


if __name__ == "__main__":
    main()
