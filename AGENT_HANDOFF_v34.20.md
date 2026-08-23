# Funeral Home Leads Intelligence Engine

> **Historical document:** This v34.20 handoff is preserved for reference and
> does not describe the current workflow. Use `README.md` and `todo.md` for
> current operation and status.

## Agent Handoff Document
## Version: v34.20

Date:
2026-07-28

---

# Project Purpose

This project is an automated funeral home digital opportunity intelligence system.

Primary objective:

Identify funeral service organizations with digital conversion weaknesses and generate actionable sales outreach packages.

The system analyzes websites, detects missing conversion features, scores opportunity value, creates executive briefs, and generates outreach assets.

---

# Current Production Version

## lead_scoring.py

Status:

✅ Stable
✅ Syntax validated
✅ Pipeline executed successfully
✅ Results exported

Validation:

python -m py_compile lead_scoring.py

Execution:

python lead_scoring.py

Output:

data/results.json


---

# Current Feature Stack

## v34.10+
Revenue intelligence layer

Capabilities:

- Revenue opportunity scoring
- Lead value scoring
- Executive prioritization


---

## v34.16

Sales Message Alignment Layer

Adds:

- sales_message_angle
- offer_angle
- executive outreach positioning


---

## v34.17

Executive Lead Brief Generator

Adds:

executive_brief

Includes:

- why_now
- recommended_first_message
- executive positioning


---

## v34.18

Outreach Asset Generator

Adds:

outreach_assets

Includes:

- email subjects
- email opening
- first email body
- phone opener
- follow-up messages


---

## v34.19

Contact Intelligence + Personalization Engine

Adds:

personalization_profile

Includes:

- website observations
- missing conversion workflows
- custom opening messages


---

## v34.20

Outreach Execution Package

Adds:

outreach_package

Structure:

email
 ├── subject
 ├── opening
 └── body

phone
 └── opening

crm
 └── next_action


---

# Current Analysis Output

File:

data/results.json


Contains:

- domain
- pages indexed
- conversion score
- opportunity score
- lead value score
- priority
- missing features
- recommended pitch
- executive action
- executive brief
- personalization profile
- outreach package


---

# Current Top Prospects

## 1. connelly-mckinley.com

Classification:

Immediate Executive Outreach

Reason:

High-value prospect with strong revenue potential and digital modernization opportunity.


Recommended angle:

Executive digital modernization assessment.


---

## 2. northernalbertafunerals.com

Classification:

Priority Sales Sequence

Weaknesses:

- No online planning workflow
- No appointment scheduling
- No live chat
- Limited lead capture


Recommended angle:

Conversion improvement package.


---

## 3. westlockfuneralhome.com

Classification:

Priority Sales Sequence

Weaknesses:

- No online planning workflow
- No appointment scheduling
- No live chat
- Limited lead capture


Recommended angle:

Conversion improvement package.


---

# Detected Opportunity Categories

Current system identifies:

- online funeral arrangement systems
- online planners
- appointment booking
- live chat
- lead capture
- consultation workflows
- preplanning workflows
- cremation information opportunities


---

# Sales Strategy

Primary offer:

Digital Funeral Conversion Modernization Package


Components:

1. Website conversion audit

2. Online arrangement workflow

3. Family inquiry automation

4. Appointment scheduling

5. AI-assisted grief support

6. Lead capture optimization


---

# Recommended Next Development Phase

## v34.21 CRM Export Layer

Build:

crm_export.py


Target outputs:

CSV
JSON
HubSpot compatible format


Fields:

- company
- domain
- priority
- executive action
- contact role
- email subject
- phone opener
- next action


---

## v34.22 Contact Discovery Layer

Add:

- owner identification
- funeral director names
- LinkedIn discovery
- email enrichment


---

## v34.23 Campaign Automation

Add:

- email sequencing
- follow-up scheduling
- campaign tracking
- response logging


---

# Important Files

Production:

lead_scoring.py

Data:

data/results.json


Supporting:

feature_detector.py
contact_ranker.py
contact_cleaner.py
outreach_export.py


---

# Known Issues

None currently blocking.

Previous issue:

pages_indexed TypeError

Cause:

data["pages"] changed from list to integer.

Fix applied:

"pages_indexed": data["pages"]


---

# Recovery

Latest stable backup:

lead_scoring.v34.20.outreach_package.backup.py


---

# Agent Instructions

When continuing:

1. Do not rewrite lead_scoring.py architecture.
2. Extend existing result schema.
3. Preserve backward compatibility with results.json.
4. Create backup before modifications.
5. Validate with py_compile.
6. Run full pipeline after changes.

Current mission:

Move from intelligence generation into CRM-ready sales execution.
