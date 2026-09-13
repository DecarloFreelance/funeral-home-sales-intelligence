import json
import tempfile
import unittest
from pathlib import Path

from build_v26_website_recovery_queue import (
    SourceValidationError,
    write_queue,
)


def portal_payload(rows):
    return {"version": "V26", "generated": "2026-09-11T00:00:00Z", "records": rows, "summary": {}}


class BuildV26WebsiteRecoveryQueueTests(unittest.TestCase):
    def test_selects_only_missing_website_rows_and_sorts_deterministically(self):
        rows = [
            {"directory_record_id": "ON-0002", "company": "B", "city": "X", "province": "ON", "website": ""},
            {"directory_record_id": "ON-0001", "company": "A", "city": "X", "province": "ON", "website": "https://a.example/"},
            {"directory_record_id": "NS-0001", "company": "C", "city": "Y", "province": "NS", "website": "   "},
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.json"
            source_bytes_before = json.dumps(portal_payload(rows)).encode()
            source.write_bytes(source_bytes_before)
            output = root / "queue.json"

            summary = write_queue(source, output)

            self.assertEqual(summary["source_total_records"], 3)
            self.assertEqual(summary["missing_website_total"], 2)
            self.assertEqual(summary["queue_written"], 2)

            queue = json.loads(output.read_text())
            self.assertEqual([row["directory_record_id"] for row in queue], ["NS-0001", "ON-0002"])
            self.assertEqual([row["directory_index"] for row in queue], [0, 1])

            # Source must never be modified.
            self.assertEqual(source.read_bytes(), source_bytes_before)

    def test_limit_bounds_queue_to_a_pilot_batch(self):
        rows = [
            {"directory_record_id": f"ON-{i:04d}", "company": f"H{i}", "city": "X", "province": "ON", "website": ""}
            for i in range(20)
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.json"
            source.write_text(json.dumps(portal_payload(rows)))
            output = root / "queue.json"

            summary = write_queue(source, output, limit=5)

            self.assertEqual(summary["missing_website_total"], 20)
            self.assertEqual(summary["queue_written"], 5)
            self.assertEqual(len(json.loads(output.read_text())), 5)

    def test_rows_missing_required_fields_are_skipped_not_fatal(self):
        rows = [
            {"directory_record_id": "ON-0001", "company": "A", "city": "X", "province": "ON", "website": ""},
            {"directory_record_id": "", "company": "B", "city": "X", "province": "ON", "website": ""},
            {"company": "C", "city": "X", "province": "ON", "website": ""},
            "not-a-dict",
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.json"
            source.write_text(json.dumps(portal_payload(rows)))
            output = root / "queue.json"

            summary = write_queue(source, output)

            self.assertEqual(summary["missing_website_total"], 1)
            self.assertEqual(json.loads(output.read_text())[0]["directory_record_id"], "ON-0001")

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

    def test_source_without_records_list_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.json"
            source.write_text(json.dumps({"version": "V26"}))
            with self.assertRaises(SourceValidationError):
                write_queue(source, root / "out.json")
            self.assertFalse((root / "out.json").exists())


if __name__ == "__main__":
    unittest.main()
