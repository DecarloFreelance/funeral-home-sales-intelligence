import csv
import json
from pathlib import Path


INPUT = Path("data/results.json")
OUTPUT = Path("data/todd_outreach_campaign.csv")


with INPUT.open() as f:
    leads = json.load(f)


with OUTPUT.open(
    "w",
    newline="",
    encoding="utf-8"
) as f:

    writer = csv.DictWriter(
        f,
        fieldnames=[
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
    )


    writer.writeheader()


    for lead in leads:

        writer.writerow({

            "company":
                lead.get("domain"),

            "website":
                "https://" + lead.get("domain"),

            "emails":
                ", ".join(
                    lead.get(
                        "emails_found",
                        []
                    )
                ),

            "phones":
                ", ".join(
                    lead.get(
                        "phones_found",
                        []
                    )
                ),

            "campaign_type":
                lead.get(
                    "campaign_type",
                    ""
                ),

            "recommended_subject":
                lead.get(
                    "recommended_subject",
                    ""
                ),

            "first_email_angle":
                lead.get(
                    "first_email_angle",
                    ""
                ),

            "seminar_fit":
                lead.get(
                    "seminar_fit",
                    0
                ),

            "sales_stage":
                lead.get(
                    "sales_stage",
                    ""
                ),

            "follow_up_priority":
                lead.get(
                    "follow_up_priority",
                    ""
                ),

            "follow_up_days":
                lead.get(
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
