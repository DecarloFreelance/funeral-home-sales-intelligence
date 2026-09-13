import json
import tempfile
import unittest
from pathlib import Path

import openpyxl

from compare_census_workbook import (
    SOURCE_XLSX,
    PORTAL_SOURCE,
    SourceValidationError,
    compare,
    load_census_rows,
    load_portal_records,
    normalize_name,
    write_comparison,
)

HEADER = (
    "Funeral Home / Location", "City", "Province", "Street Address",
    "Postal Code", "Phone", "Email", "Website", "Contact Person / Manager",
    "Type / Notes", "Source URL", "Verified / Source Date",
)


def make_workbook(path: Path, rows, sheet_name="All Canada"):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = sheet_name
    sheet.append(HEADER)
    for row in rows:
        sheet.append(row)
    workbook.save(path)


def portal_payload(records_list, version="V26"):
    return {"version": version, "generated": "2026-09-12T00:00:00Z", "records": records_list, "summary": {}}


def portal_record(company, city, province, website="", directory_record_id="ON-0001"):
    return {
        "directory_record_id": directory_record_id,
        "company": company,
        "city": city,
        "province": province,
        "website": website,
    }


class CompareCensusWorkbookTests(unittest.TestCase):
    def test_real_workbook_and_portal_produce_stable_counts(self):
        summary = compare(
            load_census_rows(SOURCE_XLSX),
            load_portal_records(PORTAL_SOURCE)[0],
        )["summary"]
        self.assertEqual(summary["census_rows"], 1077)
        self.assertEqual(summary["portal_records"], 1326)
        self.assertEqual(summary["domain_matches"], 210)
        self.assertEqual(summary["namecity_matches"], 335)
        self.assertEqual(summary["new_candidates"], 532)
        self.assertEqual(summary["new_candidates_with_website"], 156)

    def test_domain_match_wins_even_with_a_different_spelled_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            xlsx = Path(tmp) / "census.xlsx"
            make_workbook(xlsx, [(
                "Smith Bros Funerals", "Springhill", "Nova Scotia", "1 Main St",
                "B0M 1X0", "902-555-0100", "", "https://www.brownsfuneralhome.com/",
                "", "", "https://example.test/nb", "2026-09-01",
            )])
            rows = load_census_rows(xlsx)
            portal = [portal_record("A.H. Brown Funeral Services", "Springhill", "NS",
                                     website="https://www.brownsfuneralhome.com/")]
            result = compare(rows, portal)
            self.assertEqual(result["summary"]["domain_matches"], 1)
            self.assertEqual(result["summary"]["new_candidates"], 0)

    def test_namecity_match_used_when_no_website(self):
        with tempfile.TemporaryDirectory() as tmp:
            xlsx = Path(tmp) / "census.xlsx"
            make_workbook(xlsx, [(
                "Example Funeral Home", "Example City", "Ontario", "", "",
                "555-0100", "", "", "", "", "https://example.test", "2026-09-01",
            )])
            rows = load_census_rows(xlsx)
            portal = [portal_record("Example Funeral Home Ltd.", "Example City", "ON")]
            result = compare(rows, portal)
            self.assertEqual(result["summary"]["namecity_matches"], 1)
            self.assertEqual(result["summary"]["new_candidates"], 0)

    def test_unmatched_row_becomes_a_new_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            xlsx = Path(tmp) / "census.xlsx"
            make_workbook(xlsx, [(
                "Totally New Funeral Home", "Nowhere", "Alberta", "", "",
                "555-0199", "info@totallynew.example", "https://totallynew.example",
                "", "", "https://example.test", "2026-09-01",
            )])
            rows = load_census_rows(xlsx)
            result = compare(rows, [portal_record("Unrelated Home", "Elsewhere", "AB")])
            self.assertEqual(result["summary"]["new_candidates"], 1)
            candidate = result["new_candidates"][0]
            self.assertEqual(candidate["name"], "Totally New Funeral Home")
            self.assertEqual(candidate["province"], "AB")
            self.assertTrue(candidate["website"])

    def test_blank_rows_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            xlsx = Path(tmp) / "census.xlsx"
            make_workbook(xlsx, [
                (None,) * len(HEADER),
                ("Real Home", "City", "Ontario", "", "", "", "", "", "", "", "", ""),
            ])
            rows = load_census_rows(xlsx)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["name"], "Real Home")

    def test_missing_sheet_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            xlsx = Path(tmp) / "census.xlsx"
            make_workbook(xlsx, [("Home", "City", "Ontario", "", "", "", "", "", "", "", "", "")],
                          sheet_name="Something Else")
            with self.assertRaises(SourceValidationError):
                load_census_rows(xlsx, sheet_name="All Canada")

    def test_missing_workbook_refuses(self):
        with self.assertRaises(SourceValidationError):
            load_census_rows(Path("does/not/exist.xlsx"))

    def test_portal_version_mismatch_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            portal_path = Path(tmp) / "portal.json"
            portal_path.write_text(json.dumps(portal_payload([], version="V25")), encoding="utf-8")
            with self.assertRaises(SourceValidationError):
                load_portal_records(portal_path)

    def test_normalize_name_strips_suffixes_and_punctuation(self):
        self.assertEqual(normalize_name("Smith & Sons Funeral Home Ltd."), "SMITH SONS")
        self.assertEqual(normalize_name("The Smith Funeral Home, Inc."), "SMITH")

    def test_write_comparison_creates_output_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            xlsx = root / "census.xlsx"
            make_workbook(xlsx, [(
                "New Home", "City", "Ontario", "", "", "", "", "", "", "", "", "",
            )])
            portal_path = root / "portal.json"
            portal_path.write_text(json.dumps(portal_payload([])), encoding="utf-8")
            output = root / "out" / "comparison.json"

            summary = write_comparison(xlsx, portal_path, output)

            self.assertTrue(output.is_file())
            written = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(written["summary"], summary)
            self.assertEqual(summary["new_candidates"], 1)


if __name__ == "__main__":
    unittest.main()
