import csv
import json
from pathlib import Path

from intelligence.lead_intelligence import LeadIntelligence


INPUT = Path("data/results.json")
OUTPUT = Path("data/outreach_contacts.csv")


with INPUT.open() as f:
    raw_leads = json.load(f)


leads = [
    LeadIntelligence.from_result(lead)
    for lead in raw_leads
]


fields = [
    "domain",
    "lead_type",
    "sales_stage",
    "sales_readiness",
    "outreach_priority",
    "outreach_level",
    "primary_email",
    "primary_phone",
    "normalized_phone",
    "email_confidence",
    "phone_confidence",
    "phone_region_score",
    "phone_reason",
    "contact_quality_score",
    "crm_status",
    "recommended_pitch"
]


with OUTPUT.open(
    "w",
    newline="",
    encoding="utf-8"
) as f:

    writer = csv.DictWriter(
        f,
        fieldnames=fields
    )

    writer.writeheader()


    for lead in leads:

        data = lead.to_dict()

        writer.writerow({

            "domain":
                data["company"].get(
                    "domain",
                    ""
                ),

            "lead_type":
                data["company"].get(
                    "lead_type",
                    ""
                ),

            "sales_stage":
                data["scoring"].get(
                    "sales_stage",
                    ""
                ),

            "sales_readiness":
                data["scoring"].get(
                    "sales_readiness",
                    ""
                ),

            "outreach_priority":
                data["outreach"].get(
                    "outreach_priority",
                    ""
                ),

            "outreach_level":
                data["outreach"].get(
                    "outreach_level",
                    ""
                ),

            "primary_email":
                data["contacts"].get(
                    "primary_email",
                    ""
                ),

            "primary_phone":
                data["contacts"].get(
                    "primary_phone",
                    ""
                ),

            "normalized_phone":
                data["contacts"].get(
                    "normalized_phone",
                    ""
                ),

            "email_confidence":
                data["contacts"].get(
                    "email_confidence",
                    0
                ),

            "phone_confidence":
                data["contacts"].get(
                    "phone_confidence",
                    0
                ),

            "phone_region_score":
                data["contacts"].get(
                    "phone_region_score",
                    0
                ),

            "phone_reason":
                ", ".join(
                    data["contacts"].get(
                        "phone_reason",
                        []
                    )
                ),

            "contact_quality_score":
                data["contacts"].get(
                    "contact_quality_score",
                    0
                ),

            "crm_status":
                data["crm"].get(
                    "crm_status",
                    ""
                ),

            "recommended_pitch":
                data["outreach"].get(
                    "recommended_pitch",
                    ""
                )

        })


print(
    f"✅ Exported {len(leads)} outreach contacts"
)

print(
    OUTPUT
)
