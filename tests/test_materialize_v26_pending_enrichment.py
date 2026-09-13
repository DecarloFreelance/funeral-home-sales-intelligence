import json
import tempfile
import unittest
from pathlib import Path

from materialize_v26_pending_enrichment import MergeError, build_merge


def portal_payload(records_list, version="V26"):
    return {"version": version, "generated": "2026-09-12T00:00:00Z", "records": records_list, "summary": {}}


def portal_record(directory_record_id, province="AB", emails=None, phones=None, enrichment_status="pending"):
    return {
        "directory_record_id": directory_record_id, "company": "Existing", "city": "City",
        "province": province, "website": "https://existing.example/",
        "emails": emails or [], "phones": phones or [],
        "website_verification": False, "enrichment_status": enrichment_status,
    }


def jsonld_fact(field, value):
    return {"field": field, "value": value, "detector": "jsonld_localbusiness"}


def extraction_record(directory_record_id, qc_status, facts=None):
    return {"directory_record_id": directory_record_id, "qc_status": qc_status, "facts": facts or []}


def single_location_facts(city="City", province="AB"):
    return [
        jsonld_fact("address", {"city": city, "province": province}),
        jsonld_fact("email", "found@example.com"),
        jsonld_fact("phone", "555-0100"),
    ]


class MaterializeV26PendingEnrichmentTests(unittest.TestCase):
    def test_verified_record_with_empty_contact_fields_gets_filled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            extraction_path = root / "extraction.json"
            portal_path = root / "portal.json"
            extraction_path.write_text(json.dumps({"records": [
                extraction_record("AB-0001", "VERIFIED", single_location_facts()),
            ]}), encoding="utf-8")
            portal_path.write_text(json.dumps(portal_payload([portal_record("AB-0001")])), encoding="utf-8")

            merged, summary = build_merge(extraction_path, portal_path)
            record = merged["records"][0]
            self.assertEqual(record["emails"], ["found@example.com"])
            self.assertEqual(record["phones"], ["555-0100"])
            self.assertEqual(record["enrichment_status"], "verified")
            self.assertEqual(summary["updated_ids"], ["AB-0001"])

    def test_record_that_already_has_both_contact_fields_is_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            extraction_path = root / "extraction.json"
            portal_path = root / "portal.json"
            extraction_path.write_text(json.dumps({"records": [
                extraction_record("AB-0001", "VERIFIED", single_location_facts()),
            ]}), encoding="utf-8")
            existing = portal_record("AB-0001", emails=["already@example.com"], phones=["555-9999"])
            portal_path.write_text(json.dumps(portal_payload([existing])), encoding="utf-8")

            merged, summary = build_merge(extraction_path, portal_path)
            record = merged["records"][0]
            self.assertEqual(record["emails"], ["already@example.com"])
            self.assertEqual(record["phones"], ["555-9999"])
            self.assertEqual(summary["skipped_already_had_contact_evidence"], ["AB-0001"])

    def test_review_status_records_are_left_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            extraction_path = root / "extraction.json"
            portal_path = root / "portal.json"
            extraction_path.write_text(json.dumps({"records": [
                extraction_record("AB-0001", "REVIEW", single_location_facts()),
            ]}), encoding="utf-8")
            portal_path.write_text(json.dumps(portal_payload([portal_record("AB-0001")])), encoding="utf-8")

            merged, summary = build_merge(extraction_path, portal_path)
            record = merged["records"][0]
            self.assertEqual(record["emails"], [])
            self.assertEqual(summary["updated_count"], 0)

    def test_multi_location_shared_domain_suppresses_contact_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            extraction_path = root / "extraction.json"
            portal_path = root / "portal.json"
            shared_facts = [
                jsonld_fact("address", {"city": "Kamloops", "province": "BC"}),
                jsonld_fact("address", {"city": "Vernon", "province": "BC"}),
                jsonld_fact("phone", "555-0100"),
            ]
            extraction_path.write_text(json.dumps({"records": [
                extraction_record("BC-0001", "VERIFIED", shared_facts),
            ]}), encoding="utf-8")
            portal_path.write_text(json.dumps(portal_payload([portal_record("BC-0001", province="BC")])), encoding="utf-8")

            merged, summary = build_merge(extraction_path, portal_path)
            record = merged["records"][0]
            self.assertEqual(record["emails"], [])
            self.assertEqual(record["phones"], [])
            self.assertIn("BC-0001", summary["contact_fields_suppressed_multi_location"])

    def test_wrong_portal_version_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            extraction_path = root / "extraction.json"
            portal_path = root / "portal.json"
            extraction_path.write_text(json.dumps({"records": []}), encoding="utf-8")
            portal_path.write_text(json.dumps(portal_payload([], version="V25")), encoding="utf-8")
            with self.assertRaises(MergeError):
                build_merge(extraction_path, portal_path)


if __name__ == "__main__":
    unittest.main()
