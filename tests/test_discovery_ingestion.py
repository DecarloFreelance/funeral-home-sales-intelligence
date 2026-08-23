import csv
import json
import tempfile
import unittest
from pathlib import Path

from discovery.ingestion import (
    PRIORITY_PATHS,
    DiscoveryLead,
    build_crawl_queue,
    normalize_website,
)
from manual_import import import_manual_leads


class DiscoveryIngestionTests(unittest.TestCase):

    def test_normalize_website_produces_canonical_homepage(self):
        self.assertEqual(
            normalize_website(" WWW.Example.COM/about?ref=directory "),
            "https://example.com/",
        )
        self.assertEqual(normalize_website("mailto:info@example.com"), "")
        self.assertEqual(normalize_website("fostersgardenchapelcom"), "")

    def test_queue_deduplicates_domains_and_merges_sources(self):
        queue = build_crawl_queue([
            DiscoveryLead(
                company="Example Funeral Home",
                website="https://www.example.com/contact",
                city="Edmonton",
                province="ab",
                source="manual",
            ),
            DiscoveryLead(
                company="Example Funeral Home",
                website="example.com",
                phone="780-555-1234",
                source="association",
            ),
            DiscoveryLead(company="Invalid", website=""),
        ])

        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["domain"], "example.com")
        self.assertEqual(queue[0]["province"], "AB")
        self.assertEqual(queue[0]["phone"], "780-555-1234")
        self.assertEqual(queue[0]["source"], "association,manual")
        self.assertEqual(len(queue[0]["priority_urls"]), len(PRIORITY_PATHS))

    def test_manual_csv_import_writes_normalized_queue(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "manual.csv"
            output_path = Path(temp_dir) / "queue.json"

            with input_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["company", "website", "city", "province"],
                )
                writer.writeheader()
                writer.writerow({
                    "company": "Example Funeral Home",
                    "website": "www.example.com",
                    "city": "Edmonton",
                    "province": "ab",
                })
                writer.writerow({
                    "company": "Duplicate",
                    "website": "https://example.com/about",
                    "city": "",
                    "province": "",
                })

            count = import_manual_leads(input_path, output_path)
            queue = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(count, 1)
        self.assertEqual(queue[0]["url"], "https://example.com/")
        self.assertEqual(queue[0]["status"], "PENDING")

    def test_manual_csv_requires_core_columns(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "manual.csv"
            output_path = Path(temp_dir) / "queue.json"
            input_path.write_text("company\nExample\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "website"):
                import_manual_leads(input_path, output_path)


if __name__ == "__main__":
    unittest.main()
