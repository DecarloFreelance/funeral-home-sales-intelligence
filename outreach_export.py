import json
import csv
from pathlib import Path


INPUT = "data/results.json"
OUTPUT = "data/outreach_contacts.csv"


with open(INPUT, "r") as f:
    leads = json.load(f)


fields = [
    "domain",
    "lead_type",
    "sales_stage",
    "sales_readiness",
    "outreach_priority",
    "outreach_level",
    "emails_found",
    "phones_found",
    "email_angle"
]


with open(
    OUTPUT,
    "w",
    newline=""
) as f:

    writer = csv.DictWriter(
        f,
        fieldnames=fields
    )

    writer.writeheader()

    for lead in leads:

        row = {}

        for field in fields:

            value = lead.get(field, "")

            if isinstance(value, list):
                value = ", ".join(value)

            row[field] = value

        writer.writerow(row)


print(
    f"✅ Exported {len(leads)} outreach contacts"
)

print(
    OUTPUT
)
