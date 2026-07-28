You have hit the next bottleneck in the pipeline. The scoring engine is actually becoming fairly sophisticated now — the weak point is lead acquisition + entity extraction.

Right now your pipeline looks roughly like:

Crawler
   ↓
Website pages
   ↓
Feature detector
   ↓
Lead scoring
   ↓
Sales intelligence
   ↓
Outreach package

The missing layer is:

Business Discovery + Contact Intelligence

Your scraper is finding domains, but it is not building a complete business profile.

A good funeral-home lead record should eventually look like:

{
  "company": "Northern Alberta Funeral Services",
  "domain": "northernalbertafunerals.com",

  "location": {
    "address": "123 Main Street",
    "city": "Edmonton",
    "province": "AB",
    "postal_code": "T5X XXX"
  },

  "contacts": {
    "phone": [
      "780-555-5555"
    ],
    "email": [
      "info@example.com"
    ],
    "funeral_director": [
      "John Smith"
    ],
    "owner": [
      "Jane Smith"
    ]
  },

  "services": [
    "funeral services",
    "cremation",
    "pre-planning"
  ],

  "website_analysis": {
    "pages": 78,
    "missing_features": [
      "chat",
      "online_planner"
    ]
  }
}

Currently you have the bottom half. You need the top half.

Phase 1 — Improve business discovery

Right now you are probably starting with a list of domains.

Instead create a business discovery spider.

Sources:

1. Google/Bing search discovery

Generate queries:

"funeral home" Alberta
"funeral services" Calgary
"cremation services" Edmonton
"funeral director" Alberta
"pre planning funeral" Alberta

Then extract:

title
url
snippet
phone
location

Feed those URLs into your crawler.

2. Google Maps style discovery

This is probably the biggest missing source.

Search:

funeral home Calgary AB
funeral home Edmonton AB
funeral home Red Deer AB

Extract:

business name
website
phone
address
reviews
category

Your current scraper will outperform most lead tools once it has these URLs.

3. Funeral association directories

Very valuable because these already contain decision makers.

Examples:

Alberta Funeral Service Association
Canadian Funeral Association
regional directories

These give you:

company
director
address
phone
website
Phase 2 — Add manual business ingestion

You should create:

data/manual_leads.csv

Example:

company,website,city,province
Northern Alberta Funeral Services,northernalbertafunerals.com,Edmonton,AB
Legacy Funeral Home,legacyfuneralhome.ca,Calgary,AB
Example Funeral Home,example.com,Red Deer,AB

Then create:

manual_import.py

that converts it into your crawler queue.

Something like:

import csv
import json

leads=[]

with open("data/manual_leads.csv") as f:

    reader=csv.DictReader(f)

    for row in reader:
        leads.append({
            "domain": row["website"],
            "company": row["company"],
            "city": row["city"],
            "province": row["province"]
        })


with open("data/crawl_queue.json","w") as f:
    json.dump(leads,f,indent=4)

Then your crawler consumes:

crawl_queue.json
Phase 3 — Add contact extraction

This is the biggest upgrade.

Create:

contact_extractor.py

Run it against every crawled page.

Look for:

Phone numbers

Regex:

\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b

Find:

(403) 555-1234
403-555-1234
780 555 1234
Emails

Regex:

[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}
Funeral directors

This needs NLP.

Look for patterns:

Funeral Director
Managing Director
Owner
President
General Manager
Licensed Funeral Director

Example page text:

John Smith
Licensed Funeral Director
Owner

Extract:

{
"name":"John Smith",
"title":"Licensed Funeral Director"
}
Phase 4 — Crawl the right pages

Most contact data will NOT be on homepage.

Your crawler should automatically visit:

/
/contact
/contact-us
/about
/team
/staff
/funeral-directors
/our-team
/location
/locations

Add a priority queue:

priority_pages = [
    "contact",
    "about",
    "team",
    "staff",
    "directors"
]

These pages have the gold.

Phase 5 — Add schema.org extraction

Many funeral homes already expose structured data.

Search HTML for:

<script type="application/ld+json">

You can extract:

{
"name":"",
"telephone":"",
"address":"",
"email":""
}

This will instantly improve your accuracy.

Python:

from bs4 import BeautifulSoup
import json


soup = BeautifulSoup(html,"html.parser")

for script in soup.find_all(
    "script",
    type="application/ld+json"
):

    data=json.loads(script.text)

    print(data)
Phase 6 — Create a lead completeness score

Add another score:

Contact Intelligence Score

Example:

Data found	Points
Business name	10
Website	10
Phone	20
Email	20
Address	15
Funeral director	25

Maximum:

100

Then your sales priority becomes:

Opportunity Score
+
Revenue Score
+
Contact Completeness
Phase 7 — Store the missing data

Your results.json should eventually become:

{
"domain":"westlockfuneralhome.com",

"contact_intelligence":{

"phone":[
"780-555-1111"
],

"email":[
"info@westlockfuneralhome.com"
],

"people":[
{
"name":"John Doe",
"title":"Funeral Director"
}
]

}

}

Then your outreach generator can say:

Contact:
John Doe
Funeral Director

Phone:
780-555-1111

Suggested opener:

"Hi John, I was reviewing Westlock Funeral Home's online family experience..."
My recommended next version

I would make the next release:

v35.0 Contact Intelligence Engine

Structure:

funeral_home_leads/

├── discovery/
│   ├── google_search.py
│   ├── directory_scraper.py
│   └── maps_import.py

├── extraction/
│   ├── email_extractor.py
│   ├── phone_extractor.py
│   ├── person_extractor.py
│   └── schema_extractor.py

├── data/
│   ├── manual_leads.csv
│   ├── crawl_queue.json
│   └── results.json

├── lead_scoring.py
└── outreach_generator.py

The current engine is already doing the hard commercial reasoning. The next jump in quality comes from feeding it better structured businesses and decision makers.

The first thing I would build is manual_leads.csv + contact_extractor.py, because it gives immediate ROI without needing a whole discovery rewrite.
