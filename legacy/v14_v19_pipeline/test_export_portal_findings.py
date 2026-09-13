import json
import os
import tempfile
import unittest
from pathlib import Path

from export_portal_findings import MAX_RENDER_SECRET_BYTES, build, write_snapshot


class RenderDeploymentTests(unittest.TestCase):
    def fixture(self, root):
        records = []
        for index in range(955):
            records.append({
                "directory_record_id": f"CFI-{index + 1:04d}", "company": f"Home {index}",
                "city": "City", "province": "ON",
                "branch_safe_enrichment": {
                    "emails": [], "phones": [], "staff": [], "decision_makers": [],
                    "has_any_contact": False,
                },
            })
        source, summary = root / "source.json", root / "summary.json"
        source.write_text(json.dumps(records)); summary.write_text(json.dumps({"after": {"named_staff": 0}}))
        return source, summary

    def test_portal_snapshot_is_deterministic_minimal_and_under_render_limit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source, summary = self.fixture(root)
            one, two = root / "one.json", root / "two.json"
            first = write_snapshot(source, summary, one, None)
            second = write_snapshot(source, summary, two, None)
            self.assertEqual(one.read_bytes(), two.read_bytes())
            self.assertEqual(first, second)
            self.assertLess(first, MAX_RENDER_SECRET_BYTES)
            payload = json.loads(one.read_text())
            self.assertEqual(payload["version"], "V18")
            self.assertEqual(len(payload["records"]), 955)
            self.assertNotIn("source_text_sha256", one.read_text())
            if os.name != "nt":
                self.assertEqual(oct(one.stat().st_mode & 0o777), "0o600")

    def test_portal_mapping_overlay_uses_only_fresh_verified_rows(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source, summary = self.fixture(root)
            mappings = root / "mappings.json"
            mappings.write_text(json.dumps([
                {"directory_record_id": "CFI-0001", "website": "https://official.example/", "status": "VERIFIED_HIGH"},
                {"directory_record_id": "CFI-0002", "website": "https://company.ca.getstat.site/", "status": "REVIEW"},
            ]))
            payload = build(source, summary, mappings)
            self.assertEqual(payload["records"][0]["website"], "https://official.example/")
            self.assertEqual(payload["records"][1]["website"], "")

    def test_portal_snapshot_preserves_contact_context_for_inline_display(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source, summary = self.fixture(root)
            records = json.loads(source.read_text())
            records[0]["branch_safe_enrichment"]["phones"] = [{
                "value": "+12268876262", "source_url": "https://example.test/contact",
                "evidence_class": "branch-safe evidence", "evidence_line": "Contact Us · London office",
            }]
            source.write_text(json.dumps(records))
            payload = build(source, summary, None)
            self.assertEqual(payload["records"][0]["phones"][0]["evidence_line"], "Contact Us · London office")


if __name__ == "__main__":
    unittest.main()
