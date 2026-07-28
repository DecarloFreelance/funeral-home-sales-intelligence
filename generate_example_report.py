import json
from pathlib import Path

with open("data/results.json") as f:
    data = json.load(f)

lead = sorted(
    data,
    key=lambda x:x.get("executive_priority_score",0),
    reverse=True
)[0]

out = []

out.append("# Funeral Home Conversion Opportunity Report\n")

out.append(f"## Business\n{lead['domain']}\n")

out.append("## Executive Classification\n")
out.append(f"- Action: {lead['executive_action']}")
out.append(f"- Priority: {lead['priority']}")
out.append(f"- Temperature: {lead['lead_temperature']}")
out.append(f"- CRM Status: {lead['crm_status']}\n")

out.append("## Scores\n")
out.append(f"- Executive Priority: {lead['executive_priority_score']}")
out.append(f"- Opportunity Score: {lead['opportunity']}")
out.append(f"- Lead Value: {lead['lead_value']}")
out.append(f"- Revenue Opportunity: {lead['revenue_opportunity_score']}\n")

out.append("## Website Findings\n")

for item in lead["personalization_profile"]["website_observations"]:
    out.append(f"- {item}")

out.append("\n## Missing Opportunities\n")

for item in lead["missing"]:
    out.append(f"- {item}")

out.append("\n## Contact Information\n")

out.append(f"Email: {lead['primary_email']}")
out.append(f"Phone: {lead['primary_phone']}")
out.append(f"Recommended Contact: {lead['target_contact_role']}\n")


out.append("## Executive Brief\n")

for k,v in lead["executive_brief"].items():
    out.append(f"### {k}\n{v}\n")


out.append("## Outreach Package\n")

email = lead["outreach_package"]["email"]

out.append(f"Subject:\n{email['subject']}\n")
out.append(f"Opening:\n{email['opening']}\n")
out.append(f"Body:\n{email['body']}\n")


phone = lead["outreach_package"]["phone"]

out.append("## Phone Script\n")
out.append(phone["opening"])


Path(
"reports/example_output/connelly-mckinley_example_report.md"
).write_text(
    "\n".join(out),
    encoding="utf-8"
)

print(
"Created reports/example_output/connelly-mckinley_example_report.md"
)
