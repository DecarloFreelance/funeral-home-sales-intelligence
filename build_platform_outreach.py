#!/usr/bin/env python3

import argparse
import csv
from email.message import EmailMessage
import json
from pathlib import Path
import re


FORBIDDEN_CLIENT_REFERENCES = {
    "todd",
    "reinholt",
    "toddthecelebrant",
    "life celebrants international",
    "lifecelebrantsinternational",
}


PERSONALIZATION = {
    "jasontroyer.com": {
        "recipient": "Dr. Jason Troyer",
        "greeting": "Hi Jason",
        "email": "drjasontroyer@gmail.com",
        "subject": "A prospect-intelligence system for your funeral-home programs",
        "observation": "your combination of grief resources, community presentations, staff training, and funeral-home consulting",
        "value": "build and maintain a targeted North American list of funeral homes and associations that fit each program, then organize decision-maker research and follow-up",
    },
    "karithemortician.com": {
        "recipient": "Kari Northey",
        "greeting": "Hi Kari",
        "email": "kari@karithemortician.com",
        "subject": "Helping expand your funeral-service education and consulting reach",
        "observation": "your continuing education, consulting, speaking, and mortuary-school work",
        "value": "identify the schools, associations, and funeral organizations most likely to book a workshop, campus visit, or consulting engagement",
    },
    "philotimolife.com": {
        "recipient": "Maria",
        "greeting": "Hi Maria",
        "email": "info@philotimolife.com",
        "subject": "A growth system for Philotimo Life’s deathcare programs",
        "observation": "Philotimo Life’s grief-informed workshops and its consulting for funeral homes and end-of-life organizations",
        "value": "maintain separate prospect lists for funeral homes, hospices, associations, and workplace-training buyers, with each opportunity ranked for the relevant offer",
    },
    "omegafuneralconsulting.com": {
        "recipient": "Melissa Traino",
        "greeting": "Hi Melissa",
        "email": "melissa@omegafuneralconsulting.com",
        "subject": "Expanding Omega Funeral Consulting’s outreach",
        "observation": "your combination of deathcare consulting, consumer education, and speaking",
        "value": "find and organize funeral organizations, community groups, and conference opportunities that match your expertise, while keeping research and follow-up in one place",
    },
    "internationalgriefinstitute.com": {
        "recipient": "Lynda Cheldelin Fell",
        "greeting": "Hi Lynda",
        "email": "learn@internationalgriefinstitute.com",
        "subject": "Prospect intelligence for your funeral-professional training",
        "observation": "the International Grief Institute’s accredited aftercare and grief-support training for funeral professionals",
        "value": "identify funeral homes and associations that are strong candidates for certification, onsite training, or outreach resources and manage follow-up by program",
    },
    "insightbooks.com": {
        "recipient": "Glenda Stansbury",
        "greeting": "Hi Glenda",
        "email": "glenda@insightbooks.com",
        "subject": "A data partnership idea for InSight’s training and grief resources",
        "observation": "InSight’s celebrant training, grief resources, and continuing-care products",
        "value": "create continuously refreshed segments of funeral homes and associations for training sponsorships, product outreach, and celebrant-program growth",
    },
    "teamafc.com": {
        "recipient": "Melissa Drake-Messina",
        "greeting": "Hi Melissa",
        "email": "melissa@teamafc.com",
        "subject": "A funeral-sector data partnership for AFC",
        "observation": "AFC’s nationwide appraisal, succession-planning, education, and buy/sell work",
        "value": "support market development with a maintained prospect database that identifies ownership, location scale, digital signals, and public decision-maker evidence",
    },
    "facmarketing.com": {
        "recipient": "FAC Marketing team",
        "greeting": "Hello FAC Marketing team",
        "email": "info@facmarketing.com",
        "subject": "A white-label funeral prospect-data partnership",
        "observation": "FAC Marketing’s long-standing focus on independent funeral homes and crematories",
        "value": "provide a maintained prospect-intelligence feed for identifying firms by geography, website gaps, public contacts, and likely service fit",
    },
    "lindenwoodmarketing.com": {
        "recipient": "Lindenwood Marketing team",
        "greeting": "Hello Lindenwood Marketing team",
        "email": "info@lindenwoodmarketing.com",
        "subject": "Prospect intelligence for a deathcare-only agency",
        "observation": "Lindenwood’s exclusive focus on deathcare marketing and lead generation",
        "value": "add a white-label B2B prospecting system that finds funeral-sector organizations, captures public contact evidence, and prioritizes agency opportunities",
    },
    "deadringers.co": {
        "recipient": "Mandie Hungarland",
        "greeting": "Hi Mandie",
        "email": "mandie@deadringers.co",
        "subject": "A funeral-sector data partnership for Dead Ringers",
        "observation": "Dead Ringers’ deathcare mystery-shopping data, customer-experience training, and membership platform",
        "value": "add a maintained market-intelligence layer for finding funeral homes and cemeteries, organizing public business signals, and prioritizing firms for training, membership, or partnership outreach",
    },
}


def build_outreach(results, sent_emails=()):
    by_domain = {item["domain"]: item for item in results}
    sent_emails = {email.strip().lower() for email in sent_emails}
    rows = []
    for domain, draft in PERSONALIZATION.items():
        candidate = by_domain.get(domain)
        if not candidate or draft["email"] not in candidate.get("usable_emails", []):
            continue
        if draft["email"].lower() in sent_emails:
            continue
        body = (
            f"{draft['greeting']},\n\n"
            f"I came across {draft['observation']} and thought there may be a practical fit with a platform I’ve been building for the funeral sector.\n\n"
            "It combines a branded website or landing experience with a continuously maintained prospect database, public contact research, opportunity scoring, CRM actions, and follow-up tracking. "
            f"For your work, it could {draft['value']}.\n\n"
            "I’m offering the system as a managed setup and monthly license, so the data and workflows stay current without requiring your team to operate the underlying software. I’m also open to a data or white-label partnership where that makes more sense.\n\n"
            "Would you be open to a 20-minute conversation to see whether a small pilot would be useful? I can show you the working funeral-sector dataset and how the system is tailored to a specific offer.\n\n"
            "Best,\nAlex"
        )
        public_message = f"{draft['subject']}\n{body}".lower()
        leaked = sorted(
            term for term in FORBIDDEN_CLIENT_REFERENCES if term in public_message
        )
        if leaked:
            raise ValueError(
                "Client reference leaked into outreach draft: " + ", ".join(leaked)
            )
        rows.append({
            "_priority": candidate["priority_score"],
            "to": draft["email"],
            "subject": draft["subject"],
            "body": body,
        })
    rows.sort(key=lambda item: item["_priority"], reverse=True)
    for row in rows:
        del row["_priority"]
    return rows


def main():
    parser = argparse.ArgumentParser(description="Build personalized, unsent outreach drafts.")
    base = Path("data/generated/platform")
    parser.add_argument("--input", type=Path, default=base / "platform_candidate_results.json")
    parser.add_argument("--json-output", type=Path, default=base / "platform_candidate_outreach.json")
    parser.add_argument("--csv-output", type=Path, default=base / "platform_candidate_outreach.csv")
    parser.add_argument("--text-output", type=Path, default=base / "platform_candidate_outreach.txt")
    parser.add_argument("--eml-directory", type=Path, default=base / "emails")
    parser.add_argument("--history", type=Path, default=Path("data/private/outreach_history.json"))
    args = parser.parse_args()
    history = []
    if args.history.exists():
        history = json.loads(args.history.read_text(encoding="utf-8"))
    sent_emails = [
        item["email"] for item in history
        if item.get("status") == "SENT" and item.get("email")
    ]
    rows = build_outreach(
        json.loads(args.input.read_text(encoding="utf-8")),
        sent_emails,
    )
    for path in (args.json_output, args.csv_output, args.text_output):
        path.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with args.csv_output.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=["to", "subject", "body"])
        writer.writeheader()
        writer.writerows(rows)
    sections = []
    args.eml_directory.mkdir(parents=True, exist_ok=True)
    for index, row in enumerate(rows, start=1):
        sections.append(
            f"EMAIL {index}\n"
            f"To: {row['to']}\n"
            f"Subject: {row['subject']}\n\n"
            f"{row['body']}"
        )
        message = EmailMessage()
        message["To"] = row["to"]
        message["Subject"] = row["subject"]
        message.set_content(row["body"])
        filename = re.sub(r"[^a-z0-9]+", "-", row["to"].lower()).strip("-")
        (args.eml_directory / f"{index:02d}-{filename}.eml").write_bytes(
            message.as_bytes()
        )
    args.text_output.write_text(
        ("\n\n" + "=" * 72 + "\n\n").join(sections) + "\n",
        encoding="utf-8",
    )
    print(f"Prepared {len(rows)} personalized drafts; none were sent")


if __name__ == "__main__":
    main()
