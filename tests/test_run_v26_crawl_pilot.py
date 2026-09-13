import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from run_v26_crawl_pilot import PilotError, run_pilot, select_pilot_batch


def queue_entry(directory_record_id, directory_index, domain="example.com"):
    return {
        "directory_record_id": directory_record_id,
        "directory_index": directory_index,
        "company": "Example",
        "city": "City",
        "province": "ON",
        "website": f"https://{domain}/",
        "domain": domain,
        "enrichment_status": "pending",
        "queue_reason": "KNOWN_WEBSITE_NO_CONTACT_EVIDENCE",
    }


class FakeReportCrawler:
    """Stands in for PriorityPageCrawler: no network, deterministic result."""

    def crawl_queue(self, leads, on_lead=None, checkpoint=None):
        records = []
        lead_reports = []
        for lead in leads:
            item = {"url": lead["website"], "domain": lead["domain"]}
            item_report = {
                "domain": lead["domain"], "status": "SUCCESS",
                "attempts": [], "pages": 1, "duration_ms": 1,
            }
            checkpoint([item], item_report)
            records.append(item)
            lead_reports.append(item_report)
        self.last_report = {
            "queued_domains": len(leads),
            "successful_domains": len(leads),
            "failed_domains": [],
            "pages": len(records),
            "leads": lead_reports,
            "attempt_outcomes": {},
            "duration_ms": len(records),
            "average_domain_duration_ms": 1,
            "median_domain_duration_ms": 1,
        }
        return records


class RunV26CrawlPilotTests(unittest.TestCase):
    def test_selects_first_n_by_directory_index_deterministically(self):
        with tempfile.TemporaryDirectory() as temporary:
            queue_path = Path(temporary) / "queue.json"
            queue_path.write_text(json.dumps([
                queue_entry("ON-0003", 2),
                queue_entry("ON-0001", 0),
                queue_entry("ON-0002", 1),
            ]))
            batch = select_pilot_batch(queue_path, count=2)
            self.assertEqual(
                [row["directory_record_id"] for row in batch], ["ON-0001", "ON-0002"]
            )

    def test_offset_selects_a_later_slice_without_the_earlier_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            queue_path = Path(temporary) / "queue.json"
            queue_path.write_text(json.dumps([
                queue_entry("ON-0001", 0), queue_entry("ON-0002", 1),
                queue_entry("ON-0003", 2), queue_entry("ON-0004", 3),
            ]))
            batch = select_pilot_batch(queue_path, count=2, offset=2)
            self.assertEqual(
                [row["directory_record_id"] for row in batch], ["ON-0003", "ON-0004"]
            )

    def test_count_zero_selects_the_whole_queue(self):
        with tempfile.TemporaryDirectory() as temporary:
            queue_path = Path(temporary) / "queue.json"
            queue_path.write_text(json.dumps([queue_entry("ON-0001", 0), queue_entry("ON-0002", 1)]))
            batch = select_pilot_batch(queue_path, count=0)
            self.assertEqual(len(batch), 2)

    def test_run_pilot_writes_subset_queue_and_crawls_only_that_subset(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            queue_path = root / "v26_crawl_queue.json"
            queue_path.write_text(json.dumps([
                queue_entry("ON-0001", 0, domain="one.example"),
                queue_entry("ON-0002", 1, domain="two.example"),
                queue_entry("ON-0003", 2, domain="three.example"),
            ]))

            with patch("website_crawler.PriorityPageCrawler", return_value=FakeReportCrawler()):
                summary = run_pilot(
                    queue_path=queue_path,
                    count=2,
                    pilot_queue_output=root / "pilot_queue.json",
                    pages_output=root / "pilot_pages.json",
                    report_output=root / "pilot_report.json",
                )

            self.assertEqual(summary["pilot_batch_size"], 2)
            self.assertEqual(summary["queued_domains"], 2)
            self.assertEqual(summary["successful_domains"], 2)
            self.assertEqual(summary["pages"], 2)

            pilot_queue = json.loads((root / "pilot_queue.json").read_text())
            self.assertEqual(
                [row["directory_record_id"] for row in pilot_queue], ["ON-0001", "ON-0002"]
            )
            pages = json.loads((root / "pilot_pages.json").read_text())
            self.assertEqual({page["domain"] for page in pages}, {"one.example", "two.example"})

    def test_missing_queue_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(PilotError):
                select_pilot_batch(root / "missing.json", count=10)

    def test_invalid_json_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            queue_path = Path(temporary) / "queue.json"
            queue_path.write_text("{not valid")
            with self.assertRaises(PilotError):
                select_pilot_batch(queue_path, count=10)

    def test_queue_not_a_list_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            queue_path = Path(temporary) / "queue.json"
            queue_path.write_text(json.dumps({"not": "a list"}))
            with self.assertRaises(PilotError):
                select_pilot_batch(queue_path, count=10)

    def test_entry_missing_directory_index_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            queue_path = Path(temporary) / "queue.json"
            entry = queue_entry("ON-0001", 0)
            del entry["directory_index"]
            queue_path.write_text(json.dumps([entry]))
            with self.assertRaises(PilotError):
                select_pilot_batch(queue_path, count=10)


if __name__ == "__main__":
    unittest.main()
