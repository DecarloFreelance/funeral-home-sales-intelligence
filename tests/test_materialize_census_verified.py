import json
import tempfile
import unittest
from pathlib import Path

from materialize_census_verified import MergeError, build_merge


def portal_payload(records_list, version="V26"):
    return {
        "version": version,
        "generated": "2026-09-12T00:00:00Z",
        "records": records_list,
        "summary": {"total_records": len(records_list), "version": version},
    }


def portal_record(directory_record_id, province):
    return {
        "directory_record_id": directory_record_id,
        "company": "Existing", "city": "City", "province": province,
    }


def jsonld_fact(field, value, detector="jsonld_localbusiness"):
    return {"field": field, "value": value, "detector": detector}


def extraction_record(directory_record_id, company, city, province, website, qc_status, facts=None):
    return {
        "directory_record_id": directory_record_id,
        "company": company, "city": city, "province": province, "website": website,
        "qc_status": qc_status, "facts": facts or [],
    }


def single_location_facts(city, province):
    return [
        jsonld_fact("address", {"city": city, "province": province}),
        jsonld_fact("email", "info@example.com"),
        jsonld_fact("phone", "555-0100"),
    ]


class MaterializeCensusVerifiedTests(unittest.TestCase):
    def test_verified_record_gets_a_real_sequential_province_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            extraction_path = root / "extraction.json"
            portal_path = root / "portal.json"
            extraction_path.write_text(json.dumps({"records": [
                extraction_record("CENSUS-AB-0001", "New Home", "Calgary", "AB",
                                   "https://new.example/", "VERIFIED",
                                   single_location_facts("Calgary", "AB")),
            ]}), encoding="utf-8")
            portal_path.write_text(json.dumps(portal_payload([
                portal_record("AB-0005", "AB"),
            ])), encoding="utf-8")

            merged, summary = build_merge(extraction_path, portal_path)

            self.assertEqual(summary["candidates_added"], 1)
            new_record = merged["records"][-1]
            self.assertEqual(new_record["directory_record_id"], "AB-0006")
            self.assertEqual(new_record["company"], "New Home")
            self.assertEqual(new_record["emails"], ["info@example.com"])
            self.assertEqual(new_record["phones"], ["555-0100"])
            self.assertEqual(new_record["enrichment_status"], "verified")

    def test_only_verified_records_are_merged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            extraction_path = root / "extraction.json"
            portal_path = root / "portal.json"
            extraction_path.write_text(json.dumps({"records": [
                extraction_record("CENSUS-AB-0001", "Review Home", "City", "AB",
                                   "https://review.example/", "REVIEW"),
                extraction_record("CENSUS-AB-0002", "Failed Home", "City", "AB",
                                   "https://failed.example/", "UNRESOLVED"),
            ]}), encoding="utf-8")
            portal_path.write_text(json.dumps(portal_payload([])), encoding="utf-8")

            merged, summary = build_merge(extraction_path, portal_path)
            self.assertEqual(summary["candidates_added"], 0)
            self.assertEqual(len(merged["records"]), 0)

    def test_multi_location_shared_domain_suppresses_contact_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            extraction_path = root / "extraction.json"
            portal_path = root / "portal.json"
            shared_facts = [
                jsonld_fact("address", {"city": "Kamloops", "province": "BC"}),
                jsonld_fact("address", {"city": "Vernon", "province": "BC"}),
                jsonld_fact("phone", "555-0100"),
                jsonld_fact("email", "shared@example.com"),
            ]
            extraction_path.write_text(json.dumps({"records": [
                extraction_record("CENSUS-BC-0001", "Branch A", "Kamloops", "BC",
                                   "https://shared.example/", "VERIFIED", shared_facts),
            ]}), encoding="utf-8")
            portal_path.write_text(json.dumps(portal_payload([])), encoding="utf-8")

            merged, summary = build_merge(extraction_path, portal_path)
            new_record = merged["records"][0]
            self.assertEqual(new_record["emails"], [])
            self.assertEqual(new_record["phones"], [])
            self.assertEqual(new_record["city"], "Kamloops")
            self.assertIn(new_record["directory_record_id"], summary["contact_fields_suppressed_multi_location"])

    def test_provinces_summary_is_recomputed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            extraction_path = root / "extraction.json"
            portal_path = root / "portal.json"
            extraction_path.write_text(json.dumps({"records": [
                extraction_record("CENSUS-AB-0001", "New Home", "Calgary", "AB",
                                   "https://new.example/", "VERIFIED",
                                   single_location_facts("Calgary", "AB")),
            ]}), encoding="utf-8")
            portal_path.write_text(json.dumps(portal_payload([
                portal_record("AB-0001", "AB"), portal_record("BC-0001", "BC"),
            ])), encoding="utf-8")

            merged, _ = build_merge(extraction_path, portal_path)
            self.assertEqual(merged["summary"]["provinces"], {"AB": 2, "BC": 1})
            self.assertEqual(merged["summary"]["total_records"], 3)

    def test_wrong_portal_version_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            extraction_path = root / "extraction.json"
            portal_path = root / "portal.json"
            extraction_path.write_text(json.dumps({"records": []}), encoding="utf-8")
            portal_path.write_text(json.dumps(portal_payload([], version="V25")), encoding="utf-8")
            with self.assertRaises(MergeError):
                build_merge(extraction_path, portal_path)

    def test_missing_extraction_file_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            portal_path = Path(tmp) / "portal.json"
            portal_path.write_text(json.dumps(portal_payload([])), encoding="utf-8")
            with self.assertRaises(MergeError):
                build_merge(Path(tmp) / "missing.json", portal_path)


if __name__ == "__main__":
    unittest.main()
