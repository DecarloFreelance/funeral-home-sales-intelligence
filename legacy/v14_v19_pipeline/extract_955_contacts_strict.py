#!/usr/bin/env python3

import argparse
import html as html_lib
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit

from bs4 import BeautifulSoup


EMAIL_RE = re.compile(
    r"(?i)(?<![A-Z0-9._%+\-])"
    r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}"
    r"(?![A-Z0-9.\-])"
)

PHONE_RE = re.compile(
    r"(?<!\d)"
    r"(?:\+?1[\s().\-]*)?"
    r"(?:\(?\d{3}\)?[\s.\-]*)"
    r"\d{3}[\s.\-]*\d{4}"
    r"(?!\d)"
)

ROLE_RE = re.compile(
    r"(?i)\b("
    r"owner|co-owner|founder|co-founder|president|"
    r"vice president|general manager|managing director|"
    r"manager|location manager|funeral director|"
    r"licensed funeral director|managing funeral director|"
    r"director of operations|executive director|"
    r"administrator|principal|partner|operator|"
    r"embalmer|funeral arranger|preplanning director|"
    r"pre-planning director"
    r")\b"
)

DECISION_RE = re.compile(
    r"(?i)\b("
    r"owner|co-owner|founder|co-founder|president|"
    r"vice president|general manager|managing director|"
    r"manager|location manager|managing funeral director|"
    r"director of operations|executive director|"
    r"principal|partner|operator"
    r")\b"
)

NAME_TOKEN = r"[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ'’.\-]+"

NAME_RE = re.compile(
    rf"\b({NAME_TOKEN}(?:\s+{NAME_TOKEN}){{1,4}})\b"
)

BAD_NAME_PHRASES = {
    "funeral director",
    "licensed funeral director",
    "owner funeral director",
    "owner / funeral director",
    "general manager",
    "email phone",
    "email + phone",
    "research required",
    "no immediate outreach required",
    "build relationship and provide value",
    "contact us",
    "learn more",
    "read more",
    "our staff",
    "our team",
    "funeral home",
    "funeral services",
    "privacy policy",
    "terms conditions",
}

BAD_EMAIL_DOMAINS = {
    "example.com",
    "example.org",
    "sentry.io",
    "wixpress.com",
    "wordpress.com",
}

STAFF_URL_HINTS = (
    "staff",
    "team",
    "about",
    "our-people",
    "our_people",
    "people",
    "directors",
    "management",
    "who-we-are",
    "who_we_are",
)

CONTACT_URL_HINTS = (
    "contact",
    "about",
    "location",
    "locations",
    "staff",
    "team",
)


def load(path):
    return json.loads(
        Path(path).read_text(encoding="utf-8")
    )


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    tmp = path.with_suffix(
        path.suffix + ".tmp"
    )

    tmp.write_text(
        json.dumps(
            value,
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )

    os.replace(tmp, path)


def host(value):
    value = str(value or "").strip()

    if not value:
        return ""

    if "://" not in value:
        value = "https://" + value

    try:
        h = urlsplit(value).hostname or ""
    except ValueError:
        return ""

    h = h.lower().rstrip(".")

    if h.startswith("www."):
        h = h[4:]

    return h


def normalize_email(value):
    value = (
        str(value or "")
        .strip()
        .strip(".,;:()[]{}<>\"'")
        .lower()
    )

    return value


def valid_email(value):
    if not value or "@" not in value:
        return False

    local, domain = value.rsplit("@", 1)

    if not local or not domain:
        return False

    if domain in BAD_EMAIL_DOMAINS:
        return False

    if domain.endswith(".png"):
        return False

    if domain.endswith(".jpg"):
        return False

    if domain.endswith(".jpeg"):
        return False

    if domain.endswith(".gif"):
        return False

    return True


def normalize_phone(value):
    digits = re.sub(
        r"\D",
        "",
        str(value or ""),
    )

    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]

    if len(digits) != 10:
        return ""

    # NANP basic sanity.
    if digits[0] in "01" or digits[3] in "01":
        return ""

    return (
        "+1"
        + digits
    )


def page_url(page):
    if not isinstance(page, dict):
        return ""

    for key in (
        "final_url",
        "url",
        "source_url",
        "website",
        "homepage",
    ):
        value = page.get(key)

        if isinstance(value, str) and value.strip():
            return value.strip()

    return ""


def raw_page_content(page):
    if not isinstance(page, dict):
        return ""

    chunks = []

    for key in (
        "html",
        "content",
        "text",
        "body",
        "title",
    ):
        value = page.get(key)

        if isinstance(value, str) and value.strip():
            chunks.append(value)

    return "\n".join(chunks)


def visible_text(page):
    raw = raw_page_content(page)

    if not raw:
        return ""

    if re.search(r"<(?:html|body|div|p|span|section)\b", raw, re.I):
        try:
            soup = BeautifulSoup(
                raw,
                "html.parser",
            )

            for tag in soup(
                [
                    "script",
                    "style",
                    "noscript",
                    "svg",
                ]
            ):
                tag.decompose()

            raw = soup.get_text(
                "\n",
                strip=True,
            )
        except Exception:
            pass

    raw = html_lib.unescape(raw)

    lines = []

    for line in raw.splitlines():
        line = re.sub(
            r"\s+",
            " ",
            line,
        ).strip()

        if line:
            lines.append(line)

    return "\n".join(lines)


def page_domain(page):
    if isinstance(page, dict):
        explicit = page.get("domain")

        if isinstance(explicit, str):
            h = host(explicit)

            if h:
                return h

    return host(page_url(page))


def domain_matches(page_host, target):
    if page_host == target:
        return True

    # Allow www normalization already handled.
    return False


def clean_name(value):
    value = re.sub(
        r"\s+",
        " ",
        str(value or ""),
    ).strip(" -–—,:;|/")

    return value


def valid_name(value):
    value = clean_name(value)

    if not value:
        return False

    lowered = value.casefold()

    if lowered in BAD_NAME_PHRASES:
        return False

    # Reject obvious prose/UI/location/credential fragments.
    bad_fragments = (
        "funeral home",
        "funeral service",
        "cremation",
        "cemetery",
        "privacy",
        "terms ",
        "contact us",
        "read bio",
        "read more",
        "learn more",
        "our caring",
        "our staff",
        "our team",
        "license",
        "licence",
        "establishment",
        "operator class",
        "community college",
        "high school",
        "university",
        "association",
        "education",
        "coordinator",
        "celebrant",
        "mortuary science",
        "grief ",
        "livestream",
        "services",
        "avenue",
        "street",
        "road",
        "boulevard",
        "drive",
        "saskatchewan",
        "ontario",
        "alberta",
        "manitoba",
        "nova scotia",
        "new brunswick",
        "newfoundland",
        "british columbia",
        "quebec",
    )

    if any(
        fragment in lowered
        for fragment in bad_fragments
    ):
        return False

    if "@" in value:
        return False

    if re.search(
        r"https?://|www\.|\d",
        value,
        re.I,
    ):
        return False

    words = value.split()

    if not 2 <= len(words) <= 4:
        return False

    # Reject sentence fragments.
    sentence_words = {
        "he",
        "she",
        "his",
        "her",
        "when",
        "in",
        "on",
        "the",
        "our",
        "their",
        "this",
        "that",
        "with",
        "from",
        "and",
        "services",
        "owner",
        "manager",
        "director",
        "assistant",
        "retired",
        "past",
    }

    if any(
        word.casefold().strip(".,'’")
        in sentence_words
        for word in words
    ):
        return False

    # Each component must look name-like.
    good_words = 0

    for word in words:
        clean = word.strip(
            ".,'’()-"
        )

        if not clean:
            return False

        # Initials such as J. are okay.
        if re.fullmatch(
            r"[A-ZÀ-ÖØ-Þ]\.",
            clean,
        ):
            good_words += 1
            continue

        if not re.fullmatch(
            r"[A-ZÀ-ÖØ-Þ]"
            r"[A-Za-zÀ-ÖØ-öø-ÿ'’.-]+",
            clean,
        ):
            return False

        good_words += 1

    return good_words >= 2

def candidate_names(segment):
    found = []

    for match in NAME_RE.finditer(segment):
        name = clean_name(
            match.group(1)
        )

        if valid_name(name):
            found.append(name)

    return found


def extract_people_from_text(text, url):
    # Staff extraction is deliberately conservative.
    # Only use staff/team/about-style pages.
    lower_url = url.casefold()

    if not any(
        hint in lower_url
        for hint in STAFF_URL_HINTS
    ):
        return []

    people = {}

    lines = [
        re.sub(r"\s+", " ", line).strip()
        for line in text.splitlines()
        if line.strip()
    ]

    for index, line in enumerate(lines):
        role_matches = list(
            ROLE_RE.finditer(line)
        )

        # Case 1:
        # Name and role occur on the same short line.
        if role_matches and len(line) <= 160:
            for role_match in role_matches:
                role = role_match.group(0).strip()

                before = clean_name(
                    line[:role_match.start()]
                )

                after = clean_name(
                    line[role_match.end():]
                )

                candidates = []

                if valid_name(before):
                    candidates.append(before)

                if valid_name(after):
                    candidates.append(after)

                # If punctuation/text surrounds the name,
                # use regex candidates but still apply
                # strict valid_name().
                if not candidates:
                    for candidate in candidate_names(
                        line
                    ):
                        if valid_name(candidate):
                            candidates.append(
                                candidate
                            )

                for name in candidates:
                    key = (
                        name.casefold(),
                        role.casefold(),
                    )

                    people[key] = {
                        "name": name,
                        "title": role,
                        "decision_maker": bool(
                            DECISION_RE.search(role)
                        ),
                        "source_url": url,
                        "evidence_line": line[:500],
                    }

        # Case 2:
        # Common staff card layout:
        #
        #   Jane Smith
        #   Funeral Director
        #
        # Require both lines to be short.
        if valid_name(line) and len(line) <= 80:
            for offset in (1, 2):
                pos = index + offset

                if pos >= len(lines):
                    continue

                role_line = lines[pos]

                if len(role_line) > 100:
                    continue

                role_match = ROLE_RE.search(
                    role_line
                )

                if not role_match:
                    continue

                role = role_match.group(0).strip()

                key = (
                    line.casefold(),
                    role.casefold(),
                )

                people[key] = {
                    "name": line,
                    "title": role,
                    "decision_maker": bool(
                        DECISION_RE.search(role)
                    ),
                    "source_url": url,
                    "evidence_line": (
                        line
                        + " | "
                        + role_line
                    )[:500],
                }

                break

    return list(
        people.values()
    )

def is_contact_evidence_url(url):
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False

    path = (parsed.path or "/").casefold().rstrip("/")

    # Homepage is allowed.
    if path in ("", "/"):
        return True

    return any(
        hint in path
        for hint in (
            "contact",
            "location",
            "locations",
            "about",
            "staff",
            "team",
            "our-people",
            "our_people",
            "who-we-are",
            "who_we_are",
            "directory",
        )
    )


def page_contact_values(text):
    emails = set()
    phones = set()

    for match in EMAIL_RE.finditer(text):
        email = normalize_email(
            match.group(0)
        )

        if valid_email(email):
            emails.add(email)

    for match in PHONE_RE.finditer(text):
        phone = normalize_phone(
            match.group(0)
        )

        if phone:
            phones.add(phone)

    return emails, phones


def contact_quality(url):
    lower = url.casefold()

    score = 0

    if any(
        hint in lower
        for hint in CONTACT_URL_HINTS
    ):
        score += 2

    if any(
        hint in lower
        for hint in STAFF_URL_HINTS
    ):
        score += 2

    return score


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--mappings",
        required=True,
    )

    parser.add_argument(
        "--pages",
        required=True,
    )

    parser.add_argument(
        "--quarantine",
        required=True,
    )

    parser.add_argument(
        "--outdir",
        required=True,
    )

    args = parser.parse_args()

    mappings = load(args.mappings)
    pages = load(args.pages)
    quarantined = load(args.quarantine)

    quarantine_ids = {
        row["directory_record_id"]
        for row in quarantined
    }

    domain_business_counts = Counter(
        host(
            row.get("domain")
            or row.get("website")
        )
        for row in mappings
    )

    domain_pages = defaultdict(list)

    for page in pages:
        h = page_domain(page)

        if h:
            domain_pages[h].append(page)

    domain_contacts = {}

    for domain in sorted(
        {
            host(
                row.get("domain")
                or row.get("website")
            )
            for row in mappings
            if row.get("directory_record_id")
            not in quarantine_ids
        }
    ):
        if not domain:
            continue

        relevant_pages = domain_pages.get(
            domain,
            [],
        )

        emails = {}
        phones = {}
        people = {}

        for page in relevant_pages:
            url = page_url(page)
            text = visible_text(page)

            if not text:
                continue

            quality = contact_quality(url)

            # Contact values must come from a plausible
            # business-contact page, not arbitrary crawled prose,
            # obituary indexes, directories, or article archives.
            if is_contact_evidence_url(url):
                page_emails, page_phones = (
                    page_contact_values(text)
                )

                # A normal funeral-home contact/location page
                # should not contain dozens of unrelated phones.
                # Reject the page's phone evidence entirely when
                # it looks like a directory/listing corpus.
                phone_page_usable = (
                    len(page_phones) <= 15
                )

                # Likewise reject giant email lists from a single
                # page as likely directory/corporate noise.
                email_page_usable = (
                    len(page_emails) <= 30
                )

                if email_page_usable:
                    for email in page_emails:
                        existing = emails.get(email)

                        evidence = {
                            "value": email,
                            "source_url": url,
                            "page_quality": quality,
                        }

                        if (
                            existing is None
                            or quality
                            > existing["page_quality"]
                        ):
                            emails[email] = evidence

                if phone_page_usable:
                    for phone in page_phones:
                        existing = phones.get(phone)

                        evidence = {
                            "value": phone,
                            "source_url": url,
                            "page_quality": quality,
                        }

                        if (
                            existing is None
                            or quality
                            > existing["page_quality"]
                        ):
                            phones[phone] = evidence

            for person in extract_people_from_text(
                text,
                url,
            ):
                key = (
                    person["name"].casefold(),
                    person["title"].casefold(),
                )

                current = people.get(key)

                if current is None:
                    people[key] = person

                elif (
                    contact_quality(
                        person["source_url"]
                    )
                    >
                    contact_quality(
                        current["source_url"]
                    )
                ):
                    people[key] = person

        domain_contacts[domain] = {
            "domain": domain,
            "page_count": len(
                relevant_pages
            ),
            "emails": sorted(
                emails.values(),
                key=lambda row: row["value"],
            ),
            "phones": sorted(
                phones.values(),
                key=lambda row: row["value"],
            ),
            "staff": sorted(
                people.values(),
                key=lambda row: (
                    not row[
                        "decision_maker"
                    ],
                    row["name"].casefold(),
                    row["title"].casefold(),
                ),
            ),
        }

    businesses = []

    for mapping in mappings:
        record_id = mapping[
            "directory_record_id"
        ]

        if record_id in quarantine_ids:
            continue

        domain = host(
            mapping.get("domain")
            or mapping.get("website")
        )

        contact = domain_contacts.get(
            domain,
            {
                "domain": domain,
                "page_count": 0,
                "emails": [],
                "phones": [],
                "staff": [],
            },
        )

        staff = contact["staff"]

        decision_makers = [
            person
            for person in staff
            if person[
                "decision_maker"
            ]
        ]

        shared = (
            domain_business_counts[
                domain
            ] > 1
        )

        businesses.append(
            {
                "directory_record_id": record_id,
                "company": mapping.get(
                    "company"
                ),
                "city": mapping.get(
                    "city"
                ),
                "province": mapping.get(
                    "province"
                ),
                "website": mapping.get(
                    "website"
                ),
                "domain": domain,
                "verification_class": (
                    mapping.get(
                        "verification_class"
                    )
                ),
                "shared_domain": shared,
                "domain_business_count": (
                    domain_business_counts[
                        domain
                    ]
                ),
                "contact_attribution": (
                    "domain_level_needs_branch_attribution"
                    if shared
                    else "business_domain"
                ),
                "page_count": (
                    contact[
                        "page_count"
                    ]
                ),
                "emails": (
                    contact["emails"]
                ),
                "phones": (
                    contact["phones"]
                ),
                "staff": staff,
                "decision_makers": (
                    decision_makers
                ),
                "email_count": len(
                    contact["emails"]
                ),
                "phone_count": len(
                    contact["phones"]
                ),
                "staff_count": len(
                    staff
                ),
                "decision_maker_count": len(
                    decision_makers
                ),
            }
        )

    businesses.sort(
        key=lambda row: row[
            "directory_record_id"
        ]
    )

    with_pages = sum(
        row["page_count"] > 0
        for row in businesses
    )

    with_email = sum(
        row["email_count"] > 0
        for row in businesses
    )

    with_phone = sum(
        row["phone_count"] > 0
        for row in businesses
    )

    with_staff = sum(
        row["staff_count"] > 0
        for row in businesses
    )

    with_dm = sum(
        row["decision_maker_count"] > 0
        for row in businesses
    )

    with_any = sum(
        (
            row["email_count"]
            + row["phone_count"]
            + row["staff_count"]
        ) > 0
        for row in businesses
    )

    shared_records = sum(
        row["shared_domain"]
        for row in businesses
    )

    summary = {
        "verified_business_mappings": len(
            mappings
        ),
        "quarantined_businesses": len(
            quarantine_ids
        ),
        "strict_business_rows": len(
            businesses
        ),
        "coverage": {
            "with_crawled_pages": with_pages,
            "with_email": with_email,
            "with_phone": with_phone,
            "with_named_staff": with_staff,
            "with_named_decision_maker": with_dm,
            "with_any_contact": with_any,
        },
        "strict_totals": {
            "unique_email_values_by_business": sum(
                row["email_count"]
                for row in businesses
            ),
            "unique_phone_values_by_business": sum(
                row["phone_count"]
                for row in businesses
            ),
            "named_staff_by_business": sum(
                row["staff_count"]
                for row in businesses
            ),
            "named_decision_makers_by_business": sum(
                row[
                    "decision_maker_count"
                ]
                for row in businesses
            ),
        },
        "shared_domain_business_records": (
            shared_records
        ),
        "unique_contact_domains": len(
            domain_contacts
        ),
        "conservation": {
            "strict_plus_quarantine": (
                len(businesses)
                + len(quarantine_ids)
            ),
            "expected": len(mappings),
            "pass": (
                len(businesses)
                + len(quarantine_ids)
                == len(mappings)
            ),
        },
    }

    outdir = Path(args.outdir)

    atomic_json(
        outdir
        / "domain_contacts.json",
        [
            domain_contacts[key]
            for key in sorted(
                domain_contacts
            )
        ],
    )

    atomic_json(
        outdir
        / "business_contacts.json",
        businesses,
    )

    atomic_json(
        outdir
        / "coverage_summary.json",
        summary,
    )

    print(
        json.dumps(
            summary,
            indent=2,
            ensure_ascii=False,
        )
    )

    if not summary[
        "conservation"
    ]["pass"]:
        raise SystemExit(
            "conservation failed"
        )


if __name__ == "__main__":
    main()
