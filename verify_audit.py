#!/usr/bin/env python3

import json
import re
from collections import defaultdict


INPUT = "data/leads.json"


SIGNALS = {

    "contact_form": [
        "contact",
        "contact us",
        "get in touch",
        "send message"
    ],

    "appointment_booking": [
        "appointment",
        "book",
        "schedule",
        "consultation"
    ],

    "online_planner": [
        "online planner",
        "plan online",
        "online arrangement",
        "arrange online"
    ],

    "pricing": [
        "pricing",
        "price",
        "cost",
        "fees",
        "quote"
    ],

    "preplanning": [
        "pre-plan",
        "preplan",
        "plan ahead",
        "advance planning"
    ],

    "cremation": [
        "cremation"
    ],

    "burial": [
        "burial",
        "cemetery"
    ],

    "lead_capture": [
        "newsletter",
        "subscribe",
        "mailing list",
        "email"
    ],

    "chat": [
        "chat",
        "live chat",
        "intercom",
        "drift",
        "tawk"
    ]
}



def clean_domain(url):

    url = re.sub(
        r"^https?://",
        "",
        url
    )

    return url.split("/")[0].replace(
        "www.",
        ""
    )



companies = defaultdict(list)


with open(INPUT) as f:

    leads = json.load(f)


for page in leads:

    domain = clean_domain(
        page["url"]
    )

    companies[domain].append(
        page.get(
            "markdown",
            ""
        )
    )



print("\nFUNERAL HOME FEATURE VERIFICATION")
print("="*80)


for domain,pages in companies.items():

    text = "\n".join(pages).lower()


    print("\n")
    print(domain)
    print("-"*80)


    found_any = False


    for feature,keywords in SIGNALS.items():

        matches=[]


        for keyword in keywords:

            if keyword in text:

                index=text.find(keyword)

                snippet=text[
                    max(0,index-80):
                    index+150
                ]

                matches.append(
                    snippet.replace(
                        "\n",
                        " "
                    )
                )


        if matches:

            found_any=True

            print(
                f"\n✅ {feature}"
            )

            for m in matches[:2]:

                print(
                    "   ",
                    m
                )


    if not found_any:

        print(
            "❌ No conversion signals detected"
        )



print("\nDONE")
