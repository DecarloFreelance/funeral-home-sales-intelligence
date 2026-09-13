import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from build_v26_crawl_queue import (
    QUEUE_REASON,
    SourceValidationError,
    build_queue,
    normalize_hostname,
    write_queue,
)

REAL_SOURCE = Path("data/portal_findings.json")


def record(
    directory_record_id="ON-0001",
    company="Example Funeral Home",
    city="Example City",
    province="ON",
    website="https://www.example.com/",
    enrichment_status="pending",
    emails=None,
    phones=None,
    staff=None,
    decision_makers=None,
):
    return {
        "directory_record_id": directory_record_id,
        "company": company,
        "city": city,
        "province": province,
        "website": website,
        "enrichment_status": enrichment_status,
        "emails": emails if emails is not None else [],
        "phones": phones if phones is not None else [],
        "staff": staff if staff is not None else [],
        "decision_makers": decision_makers if decision_makers is not None else [],
    }


def portal_payload(records_list, version="V26"):
    return {"version": version, "generated": "2026-09-11T00:00:00Z", "records": records_list, "summary": {}}


class BuildV26CrawlQueueTests(unittest.TestCase):
    # 1. Current V26 input produces the expected current 172-record queue.
    def test_real_v26_source_produces_the_current_172_record_queue(self):
        queue, summary = build_queue(REAL_SOURCE)
        self.assertEqual(summary["queue_count"], 172)
        self.assertEqual(len(queue), 172)
        self.assertEqual(summary["source_version"], "V26")
        self.assertEqual(summary["source_total_records"], 1302)

    # 2. No-website records are excluded.
    def test_records_without_a_website_are_excluded(self):
        rows = [record(directory_record_id="ON-0001", website="")]
        queue, _ = build_queue_from_rows(rows)
        self.assertEqual(queue, [])

    # 3. Non-pending records are excluded.
    def test_non_pending_records_are_excluded(self):
        rows = [
            record(directory_record_id="ON-0001", enrichment_status="completed"),
            record(directory_record_id="ON-0002", enrichment_status="verified"),
        ]
        queue, _ = build_queue_from_rows(rows)
        self.assertEqual(queue, [])

    # 4. Pending records with any existing contact evidence are excluded.
    def test_pending_records_with_any_contact_evidence_are_excluded(self):
        rows = [
            record(directory_record_id="ON-0001", emails=["info@example.com"]),
            record(directory_record_id="ON-0002", phones=["555-0000"]),
            record(directory_record_id="ON-0003", staff=[{"name": "A"}]),
            record(directory_record_id="ON-0004", decision_makers=[{"name": "B"}]),
        ]
        queue, _ = build_queue_from_rows(rows)
        self.assertEqual(queue, [])

    # 5. Invalid/non-HTTP(S) websites are rejected -- whole run fails closed.
    def test_non_http_website_fails_closed(self):
        rows = [record(website="ftp://example.com/")]
        with self.assertRaises(SourceValidationError):
            build_queue_from_rows(rows)

    def test_malformed_website_fails_closed(self):
        rows = [record(website="not a url at all")]
        with self.assertRaises(SourceValidationError):
            build_queue_from_rows(rows)

    def test_localhost_website_fails_closed(self):
        rows = [record(website="http://localhost/")]
        with self.assertRaises(SourceValidationError):
            build_queue_from_rows(rows)

    def test_ip_literal_website_fails_closed(self):
        rows = [record(website="http://127.0.0.1/")]
        with self.assertRaises(SourceValidationError):
            build_queue_from_rows(rows)

    # 6. Domain normalization is deterministic.
    def test_domain_normalization_is_deterministic(self):
        self.assertEqual(normalize_hostname("https://WWW.Example.COM/path"), "example.com")
        self.assertEqual(normalize_hostname("http://example.com"), "example.com")
        self.assertEqual(normalize_hostname("https://sub.example.com/"), "sub.example.com")

    # 7. Duplicate domains retain separate V26 records.
    def test_duplicate_domains_are_not_merged_or_deduplicated(self):
        rows = [
            record(directory_record_id="ON-0001", company="Branch A", website="https://www.shared.example/"),
            record(directory_record_id="ON-0002", company="Branch B", website="https://shared.example/"),
        ]
        queue, summary = build_queue_from_rows(rows)
        self.assertEqual(summary["queue_count"], 2)
        ids = sorted(item["directory_record_id"] for item in queue)
        self.assertEqual(ids, ["ON-0001", "ON-0002"])
        self.assertTrue(all(item["domain"] == "shared.example" for item in queue))

    # 8. The source V26 file remains byte-for-byte unchanged.
    def test_source_file_is_never_modified(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.json"
            source.write_text(json.dumps(portal_payload([record()])))
            before = source.read_bytes()
            write_queue(source, root / "queue.json")
            self.assertEqual(source.read_bytes(), before)

        real_before = REAL_SOURCE.read_bytes()
        build_queue(REAL_SOURCE)
        self.assertEqual(REAL_SOURCE.read_bytes(), real_before)

    # 9. Output is deterministic.
    def test_output_is_deterministic_across_runs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.json"
            source.write_text(json.dumps(portal_payload([
                record(directory_record_id="ON-0002", company="B"),
                record(directory_record_id="ON-0001", company="A"),
            ])))
            one, two = root / "one.json", root / "two.json"
            write_queue(source, one)
            write_queue(source, two)
            self.assertEqual(one.read_bytes(), two.read_bytes())
            queue = json.loads(one.read_text())
            self.assertEqual([item["directory_record_id"] for item in queue], ["ON-0001", "ON-0002"])
            self.assertEqual([item["directory_index"] for item in queue], [0, 1])
            self.assertTrue(all(item["queue_reason"] == QUEUE_REASON for item in queue))

    # 10. No network access is performed.
    def test_no_network_access_is_performed(self):
        with patch("socket.getaddrinfo", side_effect=AssertionError("network access attempted")):
            build_queue(REAL_SOURCE)  # would raise if any code path resolved DNS

    # Additional fail-closed coverage, mirroring existing repository conventions.
    def test_missing_source_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(SourceValidationError):
                write_queue(root / "missing.json", root / "out.json")
            self.assertFalse((root / "out.json").exists())

    def test_invalid_json_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.json"
            source.write_text("{not valid")
            with self.assertRaises(SourceValidationError):
                write_queue(source, root / "out.json")
            self.assertFalse((root / "out.json").exists())

    def test_wrong_version_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.json"
            source.write_text(json.dumps(portal_payload([record()], version="V20")))
            with self.assertRaises(SourceValidationError):
                write_queue(source, root / "out.json")
            self.assertFalse((root / "out.json").exists())

    def test_records_not_a_list_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.json"
            source.write_text(json.dumps({"version": "V26", "records": {}}))
            with self.assertRaises(SourceValidationError):
                write_queue(source, root / "out.json")
            self.assertFalse((root / "out.json").exists())

    def test_qualifying_record_missing_identity_field_fails_closed(self):
        rows = [record(city="")]
        with self.assertRaises(SourceValidationError):
            build_queue_from_rows(rows)

    def test_qualifying_record_with_non_list_contact_field_fails_closed(self):
        # A falsy-but-non-list value (e.g. "") passes the truthiness-based
        # qualifies() check and must still be caught by the explicit type
        # check before the record is admitted to the queue.
        row = record()
        row["emails"] = ""
        with self.assertRaises(SourceValidationError):
            build_queue_from_rows([row])


def build_queue_from_rows(rows):
    with tempfile.TemporaryDirectory() as temporary:
        source = Path(temporary) / "source.json"
        source.write_text(json.dumps(portal_payload(rows)))
        return build_queue(source)


if __name__ == "__main__":
    unittest.main()
