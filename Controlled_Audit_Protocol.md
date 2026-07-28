Funeral Industry Lead Intelligence Platform — Controlled Audit Protocol

You are acting as a senior software architect and technical auditor.

Your job is to audit this repository systematically without consuming excessive context.

DO NOT attempt to audit the entire project at once.

The project goal:

Build an AI-powered funeral industry intelligence and outreach platform for Toddthecelebrant.com and Life Celebrants International.

The system should eventually:

Discover funeral homes across Canada and USA.
Collect accurate business information.
Identify decision makers and funeral directors.
Crawl and analyze funeral home websites.
Detect marketing opportunities.
Score prospects.
Generate outreach packages.
Export CRM-ready leads.
Audit Rules

Follow these rules:

Work only on ONE audit area at a time.
Do not scan unnecessary files.
Do not rewrite code yet.
Do not make assumptions without evidence.
Reference exact files and functions.
Keep reports concise.
Save findings in structured format.
Stop after completing the current audit phase.

After every audit phase provide:

Audit Phase Completed:

(name)

Files Reviewed:

(list)

Current Capability:

(what exists)

Missing Capability:

(what is missing)

Risk Level:

(Critical / High / Medium / Low)

Recommended Next Step:

(single actionable task)

Audit Roadmap

Complete the audit in this order:

================================================

PHASE 1 — Project Architecture Audit

Goal:

Understand the system structure.

Review:

README.md
requirements.txt
directory structure
major Python modules

Determine:

What the system currently does.
Main workflows.
Dependencies.
Data flow.

Do NOT inspect every function yet.

Output:

ARCHITECTURE_REPORT.md

================================================

PHASE 2 — Data Discovery Audit

Goal:

Determine how funeral homes are currently found.

Review:

Discovery logic
Scrapers
Search functions
Input datasets
Data files

Answer:

How are funeral homes discovered?
How many sources exist?
Are Google/directories/associations supported?
How is coverage measured?
What percentage of the market could realistically be captured?

Output:

DISCOVERY_AUDIT.md

================================================

PHASE 3 — Website Crawling Audit

Goal:

Determine how effectively websites are analyzed.

Review:

Crawlers
BeautifulSoup logic
Requests logic
HTML parsing
URL handling

Measure:

Can the system find:

About pages
Staff pages
Contact pages
Services
Pricing
Obituaries
Social media
Emails
Phone numbers

Output:

WEBSITE_CRAWLER_AUDIT.md

================================================

PHASE 4 — Data Extraction Audit

Goal:

Determine what information is extracted.

Create an extraction checklist:

Business:

Name
Address
Phone
Email
Website

People:

Owner
Funeral director
Staff members

Marketing:

Services offered
Technology used
Missing features
Conversion opportunities

Output:

DATA_EXTRACTION_AUDIT.md

================================================

PHASE 5 — Lead Scoring Audit

Review:

scoring.py
lead_scoring.py
revenue.py

Determine:

How leads are ranked.
Whether funeral industry priorities are represented.
Whether scoring matches Todd's business goals.

Output:

SCORING_AUDIT.md

================================================

PHASE 6 — Outreach System Audit

Review:

templates
outreach_export.py
todd_outreach_export.py
prompts.py

Determine:

What campaigns can be generated.
What information is missing.
How personalization works.

Output:

OUTREACH_AUDIT.md

================================================

PHASE 7 — Database and Scaling Audit

Determine:

Where data is stored.
Duplicate handling.
Historical tracking.
Ability to manage thousands of funeral homes.

Output:

SCALING_AUDIT.md

================================================

Important

At the end of each phase:

STOP.

Wait for approval before continuing.

Do not combine phases.

The goal is accuracy, not speed.
