#!/usr/bin/env python3

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlsplit


EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def audit_client_pages(pages):
    occurrences = {}
    for page in pages:
        url = page.get("url", "")
        domain = (urlsplit(url).hostname or "").removeprefix("www.")
        text = page.get("text") or ""
        # Visible text plus explicit mailto links avoids treating monitoring or
        # configuration addresses in third-party scripts as client contacts.
        mailto_values = re.findall(
            r"mailto:([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})",
            page.get("html") or "",
            re.I,
        )
        for email in set([*EMAIL_PATTERN.findall(text), *mailto_values]):
            key = (domain, email.lower())
            occurrences.setdefault(key, set()).add(url)

    records = []
    for (domain, email), urls in sorted(occurrences.items()):
        email_domain = email.split("@", 1)[1]
        issues = []
        if "preview-domain.com" in email_domain:
            issues.append("preview_domain_email")
        if email_domain != domain and not email_domain.endswith("." + domain):
            issues.append("domain_mismatch")
        records.append({
            "site_domain": domain,
            "email": email,
            "urls": sorted(urls),
            "issues": issues,
            "status": "REVIEW_REQUIRED" if issues else "VALID_SITE_DOMAIN",
        })

    preview = [item for item in records if "preview_domain_email" in item["issues"]]
    return {
        "status": "ISSUES_FOUND" if preview else "NO_PREVIEW_EMAIL_FOUND",
        "preview_domain_issue_confirmed": bool(preview),
        "affected_site": preview[0]["site_domain"] if preview else "",
        "affected_urls": sorted({url for item in preview for url in item["urls"]}),
        "email_records": records,
        "recommended_fix": (
            "Replace the preview-domain address in the Life Celebrants International contact-page content with todd@lifecelebrantsinternational.com."
            if preview else "No preview-domain correction required."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description="Audit client-site email consistency.")
    parser.add_argument("--input", type=Path, default=Path("data/generated/client/client_sites_crawl.json"))
    parser.add_argument("--output", type=Path, default=Path("data/generated/client/client_site_audit.json"))
    args = parser.parse_args()
    report = audit_client_pages(json.loads(args.input.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"Preview-domain issue confirmed: {report['preview_domain_issue_confirmed']}"
        f"; affected site: {report['affected_site'] or 'none'}"
    )


if __name__ == "__main__":
    main()
