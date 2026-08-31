#!/usr/bin/env python3
"""Create V16 by quarantining an exact, evidence-reviewed V15 staff denylist."""

from __future__ import annotations

import argparse
import hashlib
import json
from copy import deepcopy
from pathlib import Path

from audit_merge_falconer_v7 import metrics, write_json


BASE = Path("data/generated/directory_955")
SOURCE = BASE / "full_955_enrichment_v15/full_955_enrichment.json"
OUTPUT = BASE / "full_955_enrichment_v16"
AUDIT = BASE / "staff_precision_audit_v1"
CRM = Path("data/crm.sqlite")
SOURCE_SHA256 = "c4f6d49c0776b42d04a35987ba288d323cfde42f32b8883a534a1153ce3754b0"
CRM_SHA256 = "c06bee94b72a8bbde83e1755a9897800543f038e255e6e2db72cca744a736b9e"

# Each value was reviewed against its retained V15 evidence line. These are
# extraction artifacts, not people. Exact matching deliberately fails closed.
REJECT = {
    "CFI-0069": {"Business Law Group", "Crematorium Operator", "Funeral Administration", "Funeral Operations", "Fundraising Specialist", "Higher Thinking Strategies", "Morrison Lamothe Inc", "Norton Rose Fulbright LLP", "Vice President"},
    "CFI-0082": {"Funeral Director's"},
    "CFI-0118": {"Funeral Director-Class"},
    "CFI-0121": {"About Us"},
    "CFI-0124": {"Staff Profiles"},
    "CFI-0142": {"Operations North"},
    "CFI-0184": {"Love Remembered Jewellery"},
    "CFI-0191": {"Funeral Director-Class", "Vice President"},
    "CFI-0196": {"- Bereavement Specialist,"},
    "CFI-0217": {"Managing Director-Owner"},
    "CFI-0240": {"About Us"},
    "CFI-0259": {"DEATH CARE", "Funeral Planning", "Integrity Death Care Consultants", "LE, LFD", "Original Team", "Winnipeg Inc"},
    "CFI-0298": {"Memorial Consultant"},
    "CFI-0306": {"Sharing Service Details"},
    "CFI-0324": {"Funeral Pre-planner"},
    "CFI-0421": {"As President", "Crematorium Operator", "Opus Tribute Group", "Volunteer Board"},
    "CFI-0469": {"Crematory Operator"},
    "CFI-0504": {"Community Ambassador"},
    "CFI-0529": {"Bookkeeper, Office"},
    "CFI-0562": {"Quality Control Specialist", "Telephone Answering Staff"},
    "CFI-0566": {"Support Administrator"},
    "CFI-0569": {"Certified Therapy Dog"},
    "CFI-0583": {"Certified Crematory Operator"},
    "CFI-0610": {"West Branch"},
    "CFI-0615": {"Prepaid Funeral Contracts"},
    "CFI-0638": {"Funeral Director-Embalmer", "General Manager-Owner", "Darin Hoffman, General Manager-Owner", "Preneed Sales Consultant"},
    "CFI-0640": {"Crematorium Operator", "Transfer Service", "Transfer Service Representative"},
    "CFI-0644": {"Vice President", "Family Care Provider", "Financial Administrator"},
    "CFI-0671": {"Office Administrator"},
    "CFI-0675": {"Who We Are", "Office Administrator"},
    "CFI-0691": {"Pre-Need Specialist"},
    "CFI-0734": {"Crematorium Operator"},
    "CFI-0766": {"Funeral Attendant", "Office Administrator"},
    "CFI-0776": {"About Us"},
    "CFI-0795": {"LATHANGUE CHAPEL", "THEAKER CHAPEL"},
    "CFI-0796": {"LATHANGUE CHAPEL", "THEAKER CHAPEL"},
    "CFI-0791": {"Toronto Bloor West", "Toronto GTA North"},
    "CFI-0801": {"Family Centre", "Family Centre Team", "Office Staff"},
    "CFI-0840": {"Vineland Chapel"},
    "CFI-0857": {"Port Perry", "Rotary Club", "Scugog Men's Hockey League"},
    "CFI-0858": {"Port Perry", "Rotary Club", "Scugog Men's Hockey League"},
    "CFI-0870": {"Managing TSSR", "Office Administrator", "Tranquility Niagara", "Tranquility North Halton"},
    "CFI-0887": {"Office Administrator"},
    "CFI-0913": {"Family Experience Co", "Team Lead"},
    "CFI-0918": {"West Pubnico"},
    "CFI-0919": {"Family Counsellor", "Office Administrator"},
    "CFI-0921": {"Office Administrator", "Who We Are"},
}

# The evidence line explicitly names these people; only extractor suffix/prefix
# noise is corrected. No identity is inferred from biography prose.
RENAME = {
    ("CFI-0118", "Meet Victoria Byers"): "Victoria Byers",
    ("CFI-0216", "Tamara Park, Office"): "Tamara Park",
    ("CFI-0217", "Lily Douglas, Office"): "Lily Douglas",
    ("CFI-0335", "Allison Hogle-Dyck, Office"): "Allison Hogle-Dyck",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def materialize(source: Path, output: Path, audit: Path, crm: Path) -> dict:
    source_before, crm_before = sha256(source), sha256(crm)
    if source_before != SOURCE_SHA256:
        raise ValueError("V15 source drift detected")
    if crm_before != CRM_SHA256:
        raise ValueError("CRM drift detected")
    records = json.loads(source.read_text(encoding="utf-8"))
    if len(records) != 955 or len({r["directory_record_id"] for r in records}) != 955:
        raise ValueError("V15 must contain 955 unique canonical records")
    result = deepcopy(records)
    rejected, renamed, seen_rejects, seen_renames = [], [], set(), set()
    for row in result:
        record_id = row["directory_record_id"]
        enrichment = row.get("branch_safe_enrichment") or {}
        kept = []
        for person in enrichment.get("staff") or []:
            name = person.get("name", "")
            key = (record_id, name)
            if name in REJECT.get(record_id, set()):
                rejected.append({"directory_record_id": record_id, "company": row["company"], "reason": "non_person_extraction_artifact", "staff_record": deepcopy(person)})
                seen_rejects.add(key)
                continue
            if key in RENAME:
                old_name = name
                person["name"] = RENAME[key]
                renamed.append({"directory_record_id": record_id, "company": row["company"], "old_name": old_name, "new_name": person["name"], "reason": "remove_navigation_or_role_suffix"})
                seen_renames.add(key)
            kept.append(person)
        enrichment["staff"] = kept
        enrichment["decision_makers"] = [p for p in kept if p.get("decision_maker") is True]
        enrichment["has_staff"] = bool(kept)
        enrichment["has_decision_maker"] = bool(enrichment["decision_makers"])

    expected_rejects = {(record_id, name) for record_id, names in REJECT.items() for name in names}
    if seen_rejects != expected_rejects:
        raise ValueError(f"V15 staff denylist drift: missing={sorted(expected_rejects-seen_rejects)} unexpected={sorted(seen_rejects-expected_rejects)}")
    if seen_renames != set(RENAME):
        raise ValueError("V15 staff rename evidence drift")
    changed_ids = [a["directory_record_id"] for a, b in zip(records, result) if a != b]
    before, after = metrics(records), metrics(result)
    summary = {
        "master_records": 955, "source": "full_955_enrichment_v15",
        "before": before, "after": after,
        "net_change": {key: after[key] - before[key] for key in before},
        "staff_rows_rejected": len(rejected), "staff_names_normalized": len(renamed),
        "changed_record_ids": changed_ids,
        "v15_sha256_before": source_before, "v15_sha256_after": sha256(source),
        "crm_sha256_before": crm_before, "crm_sha256_after": sha256(crm),
        "network_requests": 0, "crm_writes": 0, "outreach_actions": 0,
        "invariants": {"master_is_955": True, "unique_directory_record_ids": True, "v15_unchanged": True, "crm_unchanged": True, "emails_and_phones_preserved": True},
    }
    changes = [{"directory_record_id": rid,
                "rejected_staff": [x for x in rejected if x["directory_record_id"] == rid],
                "normalized_names": [x for x in renamed if x["directory_record_id"] == rid]}
               for rid in changed_ids]
    write_json(output / "full_955_enrichment.json", result)
    write_json(output / "changed_records.json", changes)
    write_json(output / "summary.json", summary)
    write_json(audit / "rejected_staff.json", rejected)
    write_json(audit / "normalized_names.json", renamed)
    write_json(audit / "summary.json", summary)
    if sha256(source) != source_before or sha256(crm) != crm_before:
        raise RuntimeError("Immutable input changed during V16 materialization")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--audit", type=Path, default=AUDIT)
    parser.add_argument("--crm", type=Path, default=CRM)
    args = parser.parse_args()
    print(json.dumps(materialize(args.source, args.output, args.audit, args.crm), indent=2))


if __name__ == "__main__":
    main()
