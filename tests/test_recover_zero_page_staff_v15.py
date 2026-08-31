import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import recover_zero_page_staff_v15 as v15


class RecoverZeroPageStaffV15Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_bytes = v15.SOURCE.read_bytes()
        cls.crm_hash = hashlib.sha256(v15.CRM.read_bytes()).hexdigest()

    def run_merge(self, root):
        output, audit = root / "output", root / "audit"
        summary = v15.materialize(v15.SOURCE, v15.PAGES, output, audit, v15.CRM)
        return summary, json.loads((output / "full_955_enrichment.json").read_text()), output, audit

    def test_promotes_only_explicit_staff_with_conservative_decision_makers(self):
        with tempfile.TemporaryDirectory() as temp:
            summary, records, _output, _audit = self.run_merge(Path(temp))
        target = next(row for row in records if row["directory_record_id"] == "CFI-0753")
        staff = {row["name"]: row for row in target["branch_safe_enrichment"]["staff"]}
        self.assertEqual(len(staff), 13)
        self.assertTrue(staff["Wes Playter"]["decision_maker"])
        self.assertTrue(staff["Gregg Davey"]["decision_maker"])
        for name in ("Glenn Playter", "Allana Coolahan", "Barbara Stanek", "Jackie Playter", "Peter Fleming"):
            self.assertFalse(staff[name]["decision_maker"], name)
        self.assertEqual({row["name"] for row in target["branch_safe_enrichment"]["decision_makers"]}, {"Wes Playter", "Gregg Davey"})
        self.assertEqual(staff["Jackie Playter"]["title"], "Hostess")
        self.assertNotIn("phone", staff["Wes Playter"])
        self.assertNotIn("email", staff["Brad Bulmer"])
        self.assertEqual(summary["changed_record_ids"], ["CFI-0753"])

    def test_ignores_obituary_condolence_names_and_fax(self):
        pages = json.loads(v15.PAGES.read_text())
        staff_page = next(row for row in pages if row["url"] == v15.STAFF_URL)
        staff_page["text"] += "\nObituary: Imaginary Person\nCondolences from Random Visitor\nFax: 905-895-4747"
        # Drift protection rejects even an otherwise tempting modified cache.
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "pages.json"
            path.write_text(json.dumps(pages))
            with self.assertRaisesRegex(ValueError, "Cached evidence drift"):
                v15.load_evidence(path)

    def test_missing_or_malformed_staff_evidence_fails_closed(self):
        pages = json.loads(v15.PAGES.read_text())
        pages = [row for row in pages if row["url"] != v15.STAFF_URL]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "pages.json"
            path.write_text(json.dumps(pages))
            with self.assertRaisesRegex(ValueError, "missing"):
                v15.load_evidence(path)

    def test_source_crm_immutability_only_target_change_and_reproducibility(self):
        with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
            first = self.run_merge(Path(one))
            second = self.run_merge(Path(two))
            for filename in ("full_955_enrichment.json", "changed_records.json", "summary.json"):
                self.assertEqual((first[2] / filename).read_bytes(), (second[2] / filename).read_bytes())
            self.assertEqual((first[3] / "staff_evidence.json").read_bytes(), (second[3] / "staff_evidence.json").read_bytes())
        self.assertEqual(v15.SOURCE.read_bytes(), self.source_bytes)
        self.assertEqual(hashlib.sha256(v15.CRM.read_bytes()).hexdigest(), self.crm_hash)
        self.assertEqual(len(first[1]), 955)
        self.assertEqual(len({row["directory_record_id"] for row in first[1]}), 955)

    def test_materializer_has_no_network_or_crm_write_boundary(self):
        source = Path("recover_zero_page_staff_v15.py").read_text()
        for forbidden in ("requests.", "urlopen(", "sqlite3", "psycopg", "PsqlRunner"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
