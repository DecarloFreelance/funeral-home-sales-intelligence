# Funeral Home Leads Intelligence Platform

> **Historical document:** This v34.20 handoff is preserved for reference and
> does not describe the current workflow. Use `README.md` and `todo.md` for
> current operation and status.

## Project Handoff Document
### Current Version: v34.20
### Status: Active Development / Paused for Next Phase

---

# 1. Project Overview

## Purpose

This project is building an automated **funeral home business intelligence and sales opportunity discovery platform**.

The goal is to identify funeral homes with digital growth opportunities, analyze their online presence, score their commercial potential, and generate personalized outreach strategies.

The system is designed to answer:

- Which funeral homes are strong sales opportunities?
- What digital weaknesses exist on their websites?
- What services can be offered to improve their online conversion?
- Who should be contacted?
- What message should be used?
- What outreach channel should be prioritized?

---

# 2. Core Business Objective

The platform is designed around selling digital modernization services to funeral homes.

Primary opportunity areas:

- Online funeral arrangement systems
- Online pre-planning workflows
- Lead capture optimization
- Appointment booking systems
- AI grief/support assistants
- Chat-based family assistance
- Conversion optimization
- Digital consultation workflows

The system transforms raw websites into qualified sales intelligence.

---

# 3. Current Architecture

Current pipeline:


Website Discovery
|
↓
Website Crawling
|
↓
Feature Detection
|
↓
Lead Scoring
|
↓
Opportunity Analysis
|
↓
Executive Decision Engine
|
↓
Personalization Engine
|
↓
Outreach Package Generation
|
↓
results.json


---

# 4. Completed Development Milestones

---

# v34.0 - Core Lead Intelligence Foundation

Completed:

- Website crawling integration
- Website page analysis
- Feature detection
- Missing capability detection
- Opportunity scoring

The system can identify:

Example:


Missing:

appointment_booking
chat
lead_capture
online_planner

---

# v34.10 - Revenue Intelligence Layer

Completed:

Added revenue-focused scoring.

Tracks:

- Lead value
- Revenue opportunity
- Business potential

Example output:


Lead Value Score: 29/30
Opportunity Score: 13/15


---

# v34.11 - Decision Engine

Completed:

Added executive action classification.

Possible outcomes:


Immediate Executive Outreach

Priority Sales Sequence

Nurture Campaign

Research Queue


---

# v34.13 - JSON Export

Completed:

Structured results export.

Output:


data/results.json


Contains:

- company information
- scores
- opportunities
- recommendations
- sales intelligence

---

# v34.16 - Sales Message Alignment Layer

Completed:

Added messaging alignment.

Generates:

- sales angle
- offer angle
- first contact strategy

Example:


Sales Message Angle:

Conversion improvement opportunity

Offer Angle:

Digital conversion optimization package


---

# v34.17 - Executive Lead Brief Generator

Completed:

Creates executive summaries.

Example:


Why Now:

High-value prospect with strong revenue potential
and immediate digital modernization opportunity


Generates:

- reason for outreach
- recommended first message
- executive context

---

# v34.18 - Outreach Asset Generator

Completed:

Creates communication assets.

Generated:

Email:

- subject
- opening line
- first email body

Phone:

- call opener

Follow-up:

- day 3 message
- day 7 message

Example:


Subject:

Digital modernization opportunity for company.com


---

# v34.19 - Contact Intelligence + Personalization Engine

Completed:

Added personalized observations.

Example:


Website Observations:

No visible online planning workflow
No visible appointment scheduling workflow
No visible live chat

Generated:

Custom opening:


I reviewed your online family experience and found
several areas where improving conversion pathways
could make it easier for families to connect.


---

# v34.20 - Outreach Execution Package

Completed:

Combined sales assets into execution-ready packages.

Current output:


outreach_package

email
    subject
    opening
    body

phone
    opening

crm
    next_action

Example:


CRM:

Email | Owner / Funeral Director


---

# 5. Current Working Capabilities

The system currently successfully performs:

## Website Analysis

Can determine:

- number of pages indexed
- website features
- missing conversion tools
- digital weaknesses


## Opportunity Scoring

Calculates:

- conversion score
- opportunity score
- lead value score


## Business Prioritization

Ranks businesses by:

- sales urgency
- opportunity
- revenue potential


## Sales Intelligence

Creates:

- outreach strategy
- email messaging
- phone scripts
- CRM actions


## JSON Reporting

Current output:


data/results.json


Contains:

- scores
- recommendations
- outreach assets
- personalization
- executive briefs

---

# 6. Current Dataset

Current analysis:


Companies analysed: 18


Examples:

High priority:


connelly-mckinley.com

northernalbertafunerals.com

westlockfuneralhome.com


---

# 7. Current Limitations

The biggest remaining weakness is:

# Contact Intelligence

The system identifies businesses but does not reliably extract:

- phone numbers
- email addresses
- funeral directors
- owners
- managers
- physical addresses

Current output may show:


Company:
westlockfuneralhome.com

Opportunity:
Critical

Contact:
Missing


This prevents fully automated outreach.

---

# 8. Required Next Development Phase

## v35.0 Contact Intelligence Engine

Goal:

Turn websites into complete business profiles.

---

# Required Features

## 1. Business Discovery Engine

Currently:

Businesses are mostly manually supplied.

Need:

Automatic discovery.

Sources:

- search engines
- business directories
- funeral associations
- map listings


Output:


company
website
phone
address
category


---

# 2. Manual Lead Import

Create:


data/manual_leads.csv


Example:


company,website,city,province

Northern Alberta Funeral Services,
northernalbertafunerals.com,
Edmonton,
AB


Purpose:

Allow manual additions that automatically enter the crawler pipeline.

---

# 3. Contact Extraction Engine

Create:


contact_extractor.py


Extract:

## Email

Examples:


info@example.com
contact@example.com


---

## Phone

Examples:


403-555-5555
780-555-5555


---

## People

Detect:


Funeral Director

Owner

President

Managing Director

General Manager


Example:


John Smith

Licensed Funeral Director


---

# 4. Schema.org Extraction

Many funeral websites expose structured information.

Extract:


Business Name

Phone

Email

Address

Person


From:


application/ld+json


---

# 5. Priority Page Crawling

Improve crawler targets.

Automatically prioritize:


/contact

/contact-us

/about

/team

/staff

/funeral-directors

/locations


These pages contain the most valuable sales information.

---

# 6. Contact Completeness Score

Add:


Contact Intelligence Score


Example:

| Information | Points |
|-|-:|
| Business Name | 10 |
| Website | 10 |
| Phone | 20 |
| Email | 20 |
| Address | 15 |
| Decision Maker | 25 |

Maximum:


100


---

# 9. Future Architecture

Target pipeline:


Business Discovery
|
↓
Contact Extraction
|
↓
Website Crawl
|
↓
Feature Analysis
|
↓
Revenue Scoring
|
↓
Decision Engine
|
↓
Personalization
|
↓
CRM Export
|
↓
Outreach Automation


---

# 10. Recommended Immediate Next Steps

Priority order:

## Step 1

Build:


manual_import.py


Allow controlled business additions.

---

## Step 2

Build:


contact_extractor.py


Extract:

- emails
- phones
- directors


---

## Step 3

Modify crawler:

Add priority pages.

---

## Step 4

Add contact intelligence scoring.

---

## Step 5

Create CRM-ready exports.

Formats:

- CSV
- Excel
- HubSpot
- Salesforce compatible


---

# 11. Current Project State

The project has successfully evolved from:


Website scraper


into:


Funeral Home Sales Intelligence Platform


Completed:

✅ Website analysis  
✅ Opportunity detection  
✅ Revenue scoring  
✅ Executive prioritization  
✅ Personalized messaging  
✅ Outreach generation  


Remaining:

⬜ Automated business discovery  
⬜ Contact extraction  
⬜ Decision maker identification  
⬜ CRM integration  
⬜ Full sales automation  


---

# End State Vision

The final system should accept:


"Find funeral homes in Alberta"


and automatically produce:


100 funeral businesses

decision makers

website weaknesses

sales opportunity score

personalized email

phone script

CRM-ready lead


The platform is currently at the transition point between:

**lead scoring system**

and

**fully automated funeral industry sales intelligence platform.**
