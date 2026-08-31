#!/usr/bin/env python3
"""Materialize V15 from explicit Roadhouse & Rose staff in cached pages only."""

from __future__ import annotations

import argparse
import hashlib
import json
from copy import deepcopy
from pathlib import Path

from audit_merge_falconer_v7 import metrics, write_json


BASE = Path("data/generated/directory_955")
SOURCE = BASE / "full_955_enrichment_v14/full_955_enrichment.json"
PAGES = BASE / "zero_page_retry_v1/pages.json"
OUTPUT = BASE / "full_955_enrichment_v15"
AUDIT = BASE / "zero_page_retry_staff_audit_v1"
CRM = Path("data/crm.sqlite")
TARGET_ID = "CFI-0753"
STAFF_URL = "https://roadhouseandrose.frontrunnerpro.com/licenced_staff.html"
CONTACT_URL = "https://roadhouseandrose.frontrunnerpro.com/Contact_Information_689074.html"
SOURCE_SHA256 = "97aedaa2ec88b1672d02ae7c756c19850b4bd9d0433493d8a689eb6c2e5a40b3"
CRM_SHA256 = "c06bee94b72a8bbde83e1755a9897800543f038e255e6e2db72cca744a736b9e"
PAGE_HASHES = {
    STAFF_URL: {
        "text": "0ea3544e7fa68501b016463c561b2e29b7feca268c34d1e7d4826f939ad3d710",
        "html": "62a3a0e4a2f4ca345523e055aa09acef778f6670c1ae5fdb89c45974885edd09",
    },
    CONTACT_URL: {
        "text": "db6829c586bc45358cdf4bf5849590241f3fb84c8c82a97bab428575222901a0",
        "html": "e2ef86d2fe3990dd055a899142b26799b9bfd4e6567ed438ee28887454c0f22c",
    },
}

# Exact staff-page headings are source-drift sentinels, not a generic name extractor.
STAFF = [
    ("Wes Playter", "Funeral Director, Owner & Manager", "wes@roadhouseandrose.com", True),
    ("Gregg Davey", "Funeral Director / Owner", "gregg@roadhouseandrose.com", True),
    ("Glenn Playter", "Funeral Director", "glenn@roadhouseandrose.com", False),
    ("Jackie Playter", "Hostess", "jackie@roadhouseandrose.com", False),
    ("Juliana Playter", "Community Liaison Coordinator", "juli@roadhouseandrose.com", False),
    ("Allana Coolahan", "Funeral Director", "allana@roadhouseandrose.com", False),
    ("Herb Fowlie", "Funeral Director", "herb@roadhouseandrose.com", False),
    ("Barbara Stanek", "Assistant Funeral Director", "barb@roadhouseandrose.com", False),
    ("Helena Staruch", "Director of Advance Planning", "helena@roadhouseandrose.com", False),
    ("Spencer Ottmann", "Office Manager", "spencer@roadhouseandrose.com", False),
    ("Brad Bulmer", "Assistant Funeral Director", "", False),
    ("John Molyneaux", "Assistant Funeral Director", "", False),
    ("Peter Fleming", "Piper", "", False),
]
STAFF_HEADINGS = {
    "Wes Playter": "Wes Playter, Funeral Director, Owner & Manager",
    "Gregg Davey": "Gregg Davey, Funeral Director / Owner",
    "Glenn Playter": "Glenn Playter, Funeral Director",
    "Jackie Playter": "Jackie Playter, Roadhouse & Rose Funeral Home",
    "Juliana Playter": "Juliana Playter, Community Liaison Coordinator",
    "Allana Coolahan": "Allana Coolahan, Funeral Director",
    "Herb Fowlie": "Herb Fowlie, Funeral Director",
    "Barbara Stanek": "Barbara Stanek, Assistant Funeral Director",
    "Helena Staruch": "Helena Staruch, Director of Advance Planning",
    "Spencer Ottmann": "Spencer Ottmann, Office Manager",
    "Brad Bulmer": "Brad Bulmer, Assistant Funeral Director",
    "John Molyneaux": "John Molyneaux, Assistant Funeral Director",
    "Peter Fleming": "Peter Fleming, Piper",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalized(value: str) -> str:
    return " ".join(value.split())


def load_evidence(path: Path) -> dict[str, dict]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    pages = {row.get("url"): row for row in rows if row.get("url") in PAGE_HASHES}
    if set(pages) != set(PAGE_HASHES):
        raise ValueError("Required Roadhouse cached evidence page is missing")
    for url, expected in PAGE_HASHES.items():
        page = pages[url]
        for field in ("text", "html"):
            actual = hashlib.sha256(str(page.get(field) or "").encode()).hexdigest()
            if actual != expected[field]:
                raise ValueError(f"Cached evidence drift for {url} {field}")
    staff_text = normalized(pages[STAFF_URL]["text"])
    for marker in STAFF_HEADINGS.values():
        if normalized(marker) not in staff_text:
            raise ValueError(f"Required explicit staff evidence missing: {marker}")
    contact_text = normalized(pages[CONTACT_URL]["text"])
    for marker in (
        "Roadhouse & Rose Funeral Home 157 Main Street South Newmarket, ON",
        "Wes Playter, Funeral Director / Co-Owner / Manager",
        "Gregg Davey, Funeral Director / Co-Owner",
        "Glenn Playter, Funeral Director", "Allana Coolahan, Funeral Director",
        "Jackie Playter, Hostess",
    ):
        if normalized(marker) not in contact_text:
            raise ValueError(f"Required contact-page corroboration missing: {marker}")
    for name, _title, email, _dm in STAFF:
        if email and normalized(f"Email: {email}") not in staff_text:
            raise ValueError(f"Required explicit staff email missing: {name}")
    return pages


def materialize(source: Path, pages_path: Path, output: Path, audit: Path, crm: Path) -> dict:
    source_before = sha256(source)
    crm_before = sha256(crm)
    if source_before != SOURCE_SHA256:
        raise ValueError("V14 source drift detected")
    if crm_before != CRM_SHA256:
        raise ValueError("CRM drift detected")
    pages = load_evidence(pages_path)
    records = json.loads(source.read_text(encoding="utf-8"))
    if len(records) != 955 or len({row["directory_record_id"] for row in records}) != 955:
        raise ValueError("V14 must contain 955 unique canonical records")
    before = metrics(records)
    result = deepcopy(records)
    target = next(row for row in result if row["directory_record_id"] == TARGET_ID)
    if (target["company"], target["city"], target["province"]) != (
        "Roadhouse & Rose Funeral Home", "Newmarket", "ON"
    ):
        raise ValueError("Target canonical identity drift detected")
    enrichment = target["branch_safe_enrichment"]
    if enrichment["staff"] or enrichment["decision_makers"]:
        raise ValueError("Roadhouse V14 staff state is no longer empty")

    staff = []
    for name, title, email, decision_maker in STAFF:
        source_url = CONTACT_URL if name == "Jackie Playter" else STAFF_URL
        page = pages[source_url]
        person = {
            "name": name, "title": title, "decision_maker": decision_maker,
            "source_url": source_url, "source_file": str(pages_path),
            "source_text_sha256": hashlib.sha256(page["text"].encode()).hexdigest(),
            "source_html_sha256": hashlib.sha256(page["html"].encode()).hexdigest(),
            "evidence_class": "explicit_first_party_staff_card",
            "evidence_line": STAFF_HEADINGS[name] if name != "Jackie Playter" else "Jackie Playter, Hostess",
            "attribution_reason": "Named person appears in an explicit Roadhouse & Rose staff card.",
        }
        if email:
            person["email"] = email
        staff.append(person)
    enrichment["staff"] = staff
    enrichment["decision_makers"] = [person for person in staff if person["decision_maker"]]
    enrichment["has_staff"] = True
    enrichment["has_decision_maker"] = True
    enrichment["has_any_contact"] = True
    enrichment.setdefault("recovery_provenance", []).append({
        "pipeline": "zero_page_retry_staff_audit_v1", "classification": "BRANCH_SAFE",
        "method": "cached_explicit_first_party_staff_cards",
    })

    after = metrics(result)
    expected = dict(before)
    expected.update({
        "businesses_with_staff": before["businesses_with_staff"] + 1,
        "businesses_with_decision_maker": before["businesses_with_decision_maker"] + 1,
        "named_staff": before["named_staff"] + 13,
        "named_decision_makers": before["named_decision_makers"] + 2,
    })
    if after != expected:
        raise ValueError(f"Unexpected V15 metric change: {after}")
    changed_ids = [
        old["directory_record_id"] for old, new in zip(records, result) if old != new
    ]
    if changed_ids != [TARGET_ID]:
        raise ValueError(f"Unexpected changed records: {changed_ids}")
    changed = [{
        "directory_record_id": TARGET_ID, "company": target["company"],
        "city": target["city"], "province": target["province"],
        "added_emails": [], "added_phones": [], "staff_added": staff,
        "decision_makers_added": enrichment["decision_makers"],
    }]
    summary = {
        "master_records": 955, "source": "full_955_enrichment_v14",
        "merge_source": "zero_page_retry_staff_audit_v1", "before": before, "after": after,
        "net_gain": {key: after[key] - before[key] for key in before},
        "roadhouse_staff_added": 13, "roadhouse_decision_makers_added": 2,
        "changed_record_ids": changed_ids, "v14_sha256_before": source_before,
        "v14_sha256_after": sha256(source), "crm_sha256_before": crm_before,
        "crm_sha256_after": sha256(crm), "network_requests": 0, "crm_writes": 0,
        "invariants": {
            "master_is_955": True, "unique_directory_record_ids": True,
            "v14_unchanged": True, "crm_unchanged": True,
            "all_v14_contacts_and_people_preserved": True,
            "only_cfi_0753_changed": True, "fax_not_promoted": True,
            "generic_office_phone_not_attached_to_staff": True,
        },
    }
    evidence_audit = {
        "target": {"directory_record_id": TARGET_ID, "company": target["company"], "city": target["city"], "province": target["province"]},
        "source_file": str(pages_path),
        "pages": [{"source_url": url, "source_text_sha256": hashes["text"], "source_html_sha256": hashes["html"]} for url, hashes in PAGE_HASHES.items()],
        "promoted_staff": staff,
        "rejected": [
            {"class": "fax", "value": "+19058954747", "reason": "explicitly labeled fax"},
            {"class": "generic_shared_email", "value": "info@roadhouseandrose.com", "people": ["Brad Bulmer", "John Molyneaux"], "reason": "not an individual mailbox"},
            {"class": "biography_names", "reason": "only exact staff-card headings are eligible"},
        ],
    }
    write_json(output / "full_955_enrichment.json", result)
    write_json(output / "changed_records.json", changed)
    write_json(output / "summary.json", summary)
    write_json(audit / "staff_evidence.json", evidence_audit)
    write_json(audit / "summary.json", summary)
    if sha256(source) != source_before or sha256(crm) != crm_before:
        raise RuntimeError("Immutable input changed during V15 materialization")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--pages", type=Path, default=PAGES)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--audit", type=Path, default=AUDIT)
    parser.add_argument("--crm", type=Path, default=CRM)
    args = parser.parse_args()
    print(json.dumps(materialize(args.source, args.pages, args.output, args.audit, args.crm), indent=2))


if __name__ == "__main__":
    main()
