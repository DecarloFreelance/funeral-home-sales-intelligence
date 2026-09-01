#!/usr/bin/env python3
"""Materialize verified LangSearch websites and crawl contacts onto V18."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

BASE = Path("data/generated/directory_955")
SOURCE = BASE / "full_955_enrichment_v18/full_955_enrichment.json"
MAPPINGS = BASE / "langsearch_v3_missing_websites/crawl_v2/verified_mappings.json"
CONTACTS = BASE / "langsearch_v3_missing_websites/extraction_v2/business_contacts.json"
OUTPUT = BASE / "full_955_enrichment_v19"


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def key(item):
    return str(item.get("value") or item.get("name") or "").casefold() if isinstance(item, dict) else str(item).casefold()


def materialize(output=OUTPUT):
    result = deepcopy(load(SOURCE))
    by_id = {r["directory_record_id"]: r for r in result}
    mappings = {r["directory_record_id"]: r for r in load(MAPPINGS)}
    contacts = {r["directory_record_id"]: r for r in load(CONTACTS)}
    changed = []
    for record_id in sorted(mappings):
        target = by_id.get(record_id)
        if target is None:
            raise ValueError(f"Unknown canonical ID: {record_id}")
        mapping = mappings[record_id]
        if not target.get("website"):
            target["website"] = mapping["website"]
            target["website_status"] = "verified"
            target["website_verification"] = {
                "source": "langsearch_v3_first_party_verification",
                "verification_class": mapping.get("verification_class"),
                "verification_score": mapping.get("verification_score"),
                "domain": mapping.get("domain"),
            }
            changed.append(record_id)
        enrichment = target.setdefault("branch_safe_enrichment", {"emails": [], "phones": [], "staff": [], "decision_makers": []})
        source = contacts.get(record_id, {})
        for field in ("emails", "phones", "staff", "decision_makers"):
            existing = {key(x) for x in enrichment.get(field, [])}
            for item in source.get(field, []):
                if key(item) and key(item) not in existing:
                    enrichment.setdefault(field, []).append(item)
                    existing.add(key(item)); changed.append(record_id)
        for field in ("emails", "phones", "staff", "decision_makers"):
            enrichment[f"has_{field[:-1]}"] = bool(enrichment.get(field))
        enrichment["has_any_contact"] = bool(enrichment.get("emails") or enrichment.get("phones") or enrichment.get("staff"))
    summary = {
        "version": "V19", "source_version": "V18", "total_organizations": len(result),
        "verified_mapping_records": len(mappings), "contact_records": len(contacts),
        "records_changed": len(set(changed)), "changed_record_ids": sorted(set(changed)),
        "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "invariants": {"unique_directory_record_ids": len(by_id) == 955, "no_crm_or_outreach_writes": True},
    }
    write(output / "full_955_enrichment.json", result)
    write(output / "changed_records.json", [by_id[i] for i in summary["changed_record_ids"]])
    write(output / "summary.json", summary)
    return summary


if __name__ == "__main__":
    print(json.dumps(materialize(), indent=2))
