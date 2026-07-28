import csv
import json
from pathlib import Path

from intelligence.lead_intelligence import LeadIntelligence


INPUT = Path("data/results.json")
OUTPUT = Path("data/todd_outreach_campaign.csv")


with INPUT.open() as f:
    raw_leads = json.load(f)


leads = [
    LeadIntelligence.from_result(lead)
    for lead in raw_leads
]


fields = [
    "company",
    "website",
    "emails",
    "phones",
    "campaign_type",
    "recommended_subject",
    "first_email_angle",
    "seminar_fit",
    "sales_stage",
    "follow_up_priority",
    "follow_up_days"
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

        writer.writerow({

            "company":
                lead.company.get("domain", ""),

            "website":
                "https://" + lead.company.get(
                    "domain",
                    ""
                ),

            "emails":
                ", ".join(
                    lead.contacts.get(
                        "emails_found",
                        []
                    )
                ),

            "phones":
                ", ".join(
                    lead.contacts.get(
                        "phones_found",
                        []
                    )
                ),

            "campaign_type":
                lead.outreach.get(
                    "campaign_type",
                    ""
                ),

            "recommended_subject":
                lead.outreach.get(
                    "recommended_subject",
                    ""
                ),

            "first_email_angle":
                lead.outreach.get(
                    "first_email_angle",
                    ""
                ),

            "seminar_fit":
                lead.opportunity.get(
                    "seminar_fit",
                    0
                ),

            "sales_stage":
                lead.scoring.get(
                    "sales_stage",
                    ""
                ),

            "follow_up_priority":
                lead.outreach.get(
                    "follow_up_priority",
                    ""
                ),

            "follow_up_days":
                lead.outreach.get(
                    "follow_up_days",
                    ""
                )
        })


print(
    f"✅ Exported {len(leads)} Todd outreach prospects"
)

print(
    OUTPUT
)
