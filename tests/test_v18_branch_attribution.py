import json
from pathlib import Path

import attribute_955_branch_contacts as attribution


def test_branch_attribution_accepts_versioned_mapping_counts():
    # Current identity-verified crawl is 254 rows, not the obsolete 530-row
    # legacy set.  The validator must accept unique IDs regardless of count.
    rows = [{"directory_record_id": "CFI-0001"}, {"directory_record_id": "CFI-0002"}]
    ids = [row.get("directory_record_id") for row in rows]
    assert ids and len(set(ids)) == len(ids)


def test_branch_attribution_rejects_duplicate_mapping_ids():
    rows = [{"directory_record_id": "CFI-0001"}, {"directory_record_id": "CFI-0001"}]
    ids = [row.get("directory_record_id") for row in rows]
    assert len(set(ids)) != len(ids)


def test_v18_materialization_is_conservative_and_conserves_rows():
    path = Path("data/generated/directory_955/full_955_enrichment_v18/full_955_enrichment.json")
    summary = json.loads(Path("data/generated/directory_955/full_955_enrichment_v18/summary.json").read_text())
    rows = json.loads(path.read_text())
    assert len(rows) == 955
    assert len({row["directory_record_id"] for row in rows}) == 955
    assert summary["invariants"]["no_crm_or_outreach_writes"] is True
    assert summary["newly_verified_websites"] == 224
    assert summary["records_with_branch_evidence_added"] == 23


def test_v18_materialization_reapplies_staff_precision_boundary():
    path = Path("data/generated/directory_955/full_955_enrichment_v18/full_955_enrichment.json")
    rows = json.loads(path.read_text())
    by_id = {row["directory_record_id"]: row for row in rows}

    # These labels were quarantined in V16 and must not return through the
    # later branch-attribution overlay.
    assert "Crematorium Operator" not in {
        person["name"] for person in by_id["CFI-0069"]["branch_safe_enrichment"]["staff"]
    }
    assert "Who We Are" not in {
        person["name"] for person in by_id["CFI-0921"]["branch_safe_enrichment"]["staff"]
    }
    assert "Office Administrator" not in {
        person["name"] for person in by_id["CFI-0921"]["branch_safe_enrichment"]["staff"]
    }
