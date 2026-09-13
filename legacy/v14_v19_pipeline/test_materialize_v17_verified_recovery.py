import hashlib
import json
import tempfile
from pathlib import Path

import materialize_v17_verified_recovery as v17


def test_v17_is_deterministic_and_preserves_reviewed_canonical_state():
    v16_before = hashlib.sha256(v17.SOURCE.read_bytes()).hexdigest()
    crm_before = hashlib.sha256(v17.CRM.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory() as temp:
        first = Path(temp) / "first"
        second = Path(temp) / "second"
        summary = v17.materialize(first)
        v17.materialize(second)
        assert (first / "full_955_enrichment.json").read_bytes() == (second / "full_955_enrichment.json").read_bytes()
        rows = {row["directory_record_id"]: row for row in json.loads((first / "full_955_enrichment.json").read_text())}
        assert rows["CFI-0756"]["website_status"] == "under_review"
        assert rows["CFI-0658"]["branch_safe_enrichment"]["emails"][0]["value"] == "info@nbardal.mb.ca"
        assert rows["CFI-0658"]["branch_safe_enrichment"]["phones"][0]["value"] == "+12049492200"
        assert summary["records_changed_from_v16"] == 26
        assert summary["crm_writes"] == summary["outreach_actions"] == 0
    assert hashlib.sha256(v17.SOURCE.read_bytes()).hexdigest() == v16_before
    assert hashlib.sha256(v17.CRM.read_bytes()).hexdigest() == crm_before
