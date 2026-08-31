import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import sanitize_staff_precision_v16 as v16


class SanitizeStaffPrecisionV16Tests(unittest.TestCase):
    def run_merge(self, root):
        output, audit = root / "output", root / "audit"
        summary = v16.materialize(v16.SOURCE, output, audit, v16.CRM)
        records = json.loads((output / "full_955_enrichment.json").read_text())
        return summary, records, output, audit

    def test_quarantines_non_people_and_retains_real_staff(self):
        with tempfile.TemporaryDirectory() as temp:
            summary, records, _output, _audit = self.run_merge(Path(temp))
        by_id = {row["directory_record_id"]: row for row in records}
        names = lambda rid: {p["name"] for p in by_id[rid]["branch_safe_enrichment"]["staff"]}
        self.assertNotIn("Norton Rose Fulbright LLP", names("CFI-0069"))
        self.assertNotIn("Crematorium Operator", names("CFI-0421"))
        self.assertNotIn("Who We Are", names("CFI-0675"))
        self.assertNotIn("Rotary Club", names("CFI-0857"))
        self.assertIn("Wes Playter", names("CFI-0753"))
        self.assertIn("Gregg Davey", names("CFI-0753"))
        self.assertIn("Glenn Playter", names("CFI-0753"))
        self.assertIn("Allana Coolahan", names("CFI-0753"))
        self.assertIn("Victoria Byers", names("CFI-0118"))
        self.assertEqual(summary["staff_rows_rejected"], 89)
        self.assertEqual(summary["after"]["named_staff"], 629)
        self.assertEqual(summary["after"]["named_decision_makers"], 204)

    def test_contacts_and_road_house_decision_policy_are_preserved(self):
        original = json.loads(v16.SOURCE.read_text())
        with tempfile.TemporaryDirectory() as temp:
            _summary, records, _output, _audit = self.run_merge(Path(temp))
        for before, after in zip(original, records):
            a, b = before["branch_safe_enrichment"], after["branch_safe_enrichment"]
            self.assertEqual(a.get("emails"), b.get("emails"))
            self.assertEqual(a.get("phones"), b.get("phones"))
        road = next(r for r in records if r["directory_record_id"] == "CFI-0753")
        self.assertEqual({p["name"] for p in road["branch_safe_enrichment"]["decision_makers"]}, {"Wes Playter", "Gregg Davey"})

    def test_source_drift_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source.json"
            source.write_bytes(v16.SOURCE.read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "source drift"):
                v16.materialize(source, Path(temp) / "out", Path(temp) / "audit", v16.CRM)

    def test_reproducible_and_immutable(self):
        source_hash, crm_hash = hashlib.sha256(v16.SOURCE.read_bytes()).hexdigest(), hashlib.sha256(v16.CRM.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
            first = self.run_merge(Path(one)); second = self.run_merge(Path(two))
            for filename in ("full_955_enrichment.json", "changed_records.json", "summary.json"):
                self.assertEqual((first[2] / filename).read_bytes(), (second[2] / filename).read_bytes())
            self.assertEqual((first[3] / "rejected_staff.json").read_bytes(), (second[3] / "rejected_staff.json").read_bytes())
        self.assertEqual(source_hash, hashlib.sha256(v16.SOURCE.read_bytes()).hexdigest())
        self.assertEqual(crm_hash, hashlib.sha256(v16.CRM.read_bytes()).hexdigest())
        self.assertEqual(len(first[1]), 955)

    def test_no_network_database_or_outreach_boundary(self):
        source = Path("sanitize_staff_precision_v16.py").read_text()
        for forbidden in ("requests.", "urlopen(", "sqlite3", "psycopg", "send_message"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
