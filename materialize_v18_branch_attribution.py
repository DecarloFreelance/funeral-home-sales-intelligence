#!/usr/bin/env python3
"""Materialize a conservative V18 overlay from identity-verified branch evidence."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from sanitize_staff_precision_v16 import REJECT, RENAME


BASE = Path("data/generated/directory_955")
SOURCE = BASE / "full_955_enrichment_v17/full_955_enrichment.json"
BRANCH = BASE / "branch_attribution_v2/branch_contacts.json"
MAPPINGS = BASE / "legacy_mapping_crawl_v2/verified_mappings.json"
OUTPUT = BASE / "full_955_enrichment_v18"


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def value_key(item):
    if isinstance(item, dict):
        return str(item.get("value") or item.get("name") or "").casefold()
    return str(item).casefold()


def materialize(output=OUTPUT):
    original = load(SOURCE)
    result = deepcopy(original)
    by_id = {row["directory_record_id"]: row for row in result}
    branches = {row["directory_record_id"]: row for row in load(BRANCH)}
    mappings = {row["directory_record_id"]: row for row in load(MAPPINGS)}
    changed = []
    website_changes = []
    evidence_changes = []

    for record_id, mapping in mappings.items():
        target = by_id.get(record_id)
        branch = branches.get(record_id)
        if target is None or branch is None:
            continue

        if not target.get("website") and mapping.get("website"):
            target["website"] = mapping["website"]
            target["website_status"] = "verified"
            target["website_verification"] = {
                "source": "legacy_mapping_crawl_v2_identity_verified",
                "domain": mapping.get("domain"),
                "verification_class": mapping.get("verification_class"),
                "verification_score": mapping.get("verification_score"),
            }
            website_changes.append(record_id)

        enrichment = target.setdefault("branch_safe_enrichment", {
            "emails": [], "phones": [], "staff": [], "decision_makers": [],
        })
        record_added = False
        for field in ("emails", "phones", "staff", "decision_makers"):
            existing = {value_key(item) for item in enrichment.get(field, [])}
            added = 0
            for item in branch.get(field, []):
                key = value_key(item)
                if not key or key in existing:
                    continue
                enrichment.setdefault(field, []).append(item)
                existing.add(key)
                added += 1
            if added:
                record_added = True
                evidence_changes.append({"directory_record_id": record_id, "field": field, "added": added})

        # Branch overlays are produced by a separate extractor and therefore
        # must pass the same evidence-reviewed precision boundary as V16.
        # Apply exact, record-scoped quarantine and name normalization only;
        # do not infer or discard any other person records here.
        kept_staff = []
        for person in enrichment.get("staff", []):
            name = person.get("name", "") if isinstance(person, dict) else ""
            if name in REJECT.get(record_id, set()):
                continue
            rename_key = (record_id, name)
            if rename_key in RENAME:
                person = deepcopy(person)
                person["name"] = RENAME[rename_key]
            kept_staff.append(person)
        enrichment["staff"] = kept_staff
        enrichment["decision_makers"] = [
            person for person in kept_staff
            if isinstance(person, dict) and person.get("decision_maker") is True
        ]

        for field in ("emails", "phones", "staff", "decision_makers"):
            enrichment[f"has_{field[:-1]}"] = bool(enrichment.get(field))
        enrichment["has_any_contact"] = bool(
            enrichment.get("emails") or enrichment.get("phones") or enrichment.get("staff")
        )
        if record_added and record_id not in changed:
            changed.append(record_id)

    changed = sorted(set(changed) | set(website_changes))
    summary = {
        "version": "V18",
        "source": "full_955_enrichment_v17",
        "total_organizations": len(result),
        "verified_mapping_records": len(mappings),
        "newly_verified_websites": len(website_changes),
        "records_with_branch_evidence_added": len({x["directory_record_id"] for x in evidence_changes}),
        "evidence_field_additions": evidence_changes,
        "records_changed": len(changed),
        "changed_record_ids": changed,
        "source_sha256": hashlib.sha256(Path(SOURCE).read_bytes()).hexdigest(),
        "invariants": {
            "unique_directory_record_ids": len(by_id) == 955,
            "no_crm_or_outreach_writes": True,
        },
    }
    write(output / "full_955_enrichment.json", result)
    write(output / "changed_records.json", [by_id[i] for i in changed])
    write(output / "summary.json", summary)
    return summary


if __name__ == "__main__":
    print(json.dumps(materialize(), indent=2))
