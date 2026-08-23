#!/usr/bin/env python3

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

from feature_detector import FEATURE_PATTERNS, detect_features


parser = argparse.ArgumentParser(
    description="Print conversion-feature evidence from a crawled page dataset."
)
parser.add_argument(
    "--input", type=Path, default=Path("data/generated/campaign/leads.json")
)
args = parser.parse_args()
INPUT = args.input
if not INPUT.is_file():
    parser.error(f"crawl input does not exist: {INPUT}")


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


with INPUT.open(encoding="utf-8") as f:

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


    scores = detect_features(text)
    detected = {
        feature: score for feature, score in scores.items() if score >= 3
    }

    for feature, score in detected.items():
        print(f"\n✅ {feature} (score {score})")
        snippets = []
        for pattern in FEATURE_PATTERNS.get(feature, {}):
            match = re.search(pattern, text)
            if match:
                snippets.append(
                    text[max(0, match.start() - 80):match.end() + 150]
                    .replace("\n", " ")
                )
        for snippet in snippets[:2]:
            print("   ", snippet)


    if not detected:

        print(
            "❌ No conversion signals detected"
        )



print("\nDONE")
