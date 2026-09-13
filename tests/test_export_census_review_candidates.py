import csv
import json
import tempfile
import unittest
from pathlib import Path

from export_census_review_candidates import SourceValidationError, write_exports


def extraction_payload(records_list):
    return {"records": records_list}


def comparison_payload(new_candidates):
    return {"new_candidates": new_candidates}


class ExportCensusReviewCandidatesTests(unittest.TestCase):
    def test_only_review_status_records_are_exported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            extraction_path = root / "extraction.json"
            comparison_path = root / "comparison.json"
            extraction_path.write_text(json.dumps(extraction_payload([
                {"directory_record_id": "CENSUS-AB-0001", "company": "Review Home", "city": "City",
                 "province": "AB", "website": "https://example.test/", "qc_status": "REVIEW",
                 "facts": [{"field": "email", "value": "a@example.test"}, {"field": "phone", "value": "555-0100"}],
                 "qc_reasons": ["no_structured_facts:static_text_pattern"]},
                {"directory_record_id": "CENSUS-AB-0002", "company": "Verified Home", "city": "City",
                 "province": "AB", "website": "https://v.example/", "qc_status": "VERIFIED", "facts": []},
            ])), encoding="utf-8")
            comparison_path.write_text(json.dumps(comparison_payload([])), encoding="utf-8")

            review_output = root / "review.csv"
            no_website_output = root / "no_website.csv"
            summary = write_exports(extraction_path, comparison_path, review_output, no_website_output)

            self.assertEqual(summary["review_count"], 1)
            rows = list(csv.DictReader(review_output.open(encoding="utf-8")))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["company"], "Review Home")
            self.assertEqual(rows[0]["emails_found"], "a@example.test")
            self.assertEqual(rows[0]["phones_found"], "555-0100")

    def test_only_no_website_candidates_are_exported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            extraction_path = root / "extraction.json"
            comparison_path = root / "comparison.json"
            extraction_path.write_text(json.dumps(extraction_payload([])), encoding="utf-8")
            comparison_path.write_text(json.dumps(comparison_payload([
                {"name": "No Site Home", "city": "City", "province": "AB", "phone": "555-0100", "website": ""},
                {"name": "Has Site Home", "city": "City", "province": "AB", "phone": "555-0200",
                 "website": "https://example.test/"},
            ])), encoding="utf-8")

            review_output = root / "review.csv"
            no_website_output = root / "no_website.csv"
            summary = write_exports(extraction_path, comparison_path, review_output, no_website_output)

            self.assertEqual(summary["no_website_count"], 1)
            rows = list(csv.DictReader(no_website_output.open(encoding="utf-8")))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["name"], "No Site Home")

    def test_missing_extraction_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            comparison_path = root / "comparison.json"
            comparison_path.write_text(json.dumps(comparison_payload([])), encoding="utf-8")
            with self.assertRaises(SourceValidationError):
                write_exports(root / "missing.json", comparison_path, root / "r.csv", root / "n.csv")


if __name__ == "__main__":
    unittest.main()
