import csv
import json
import tempfile
import unittest
from pathlib import Path

from discovery.ingestion import (
    MALFORMED_WEBSITE_USERINFO,
    PRIORITY_PATHS,
    DiscoveryLead,
    build_crawl_queue,
    normalize_website,
)
from discovery.source_adapters import adapt_record
from manual_import import import_manual_leads


class DiscoveryIngestionTests(unittest.TestCase):

    def test_normalize_website_produces_canonical_homepage(self):
        self.assertEqual(
            normalize_website(" WWW.Example.COM/about?ref=directory "),
            "https://example.com/",
        )
        self.assertEqual(normalize_website("mailto:info@example.com"), "")
        self.assertEqual(normalize_website("fostersgardenchapelcom"), "")
        self.assertEqual(normalize_website("http://www.fostermcgarvey.com"), "http://fostermcgarvey.com/")
        self.assertEqual(normalize_website("https://www.example.com/path"), "https://example.com/")
        for malformed in (
            "http://info@example.com",
            "https://office@example.com",
            "http://person@domain.tld",
        ):
            self.assertEqual(normalize_website(malformed), "", malformed)
        for unsafe in (
            "http://127.0.0.1:8080", "http://169.254.169.254/latest/meta-data",
            "http://10.0.0.1", "http://service.local/", "http://localhost/",
        ):
            self.assertEqual(normalize_website(unsafe), "", unsafe)

    def test_malformed_website_userinfo_is_flagged_without_canonical_identity(self):
        lead = adapt_record({
            "company": "Foster and McGarvey Ltd",
            "website": "http://info@fostercmgarvey.com",
            "email": "info@fostercmgarvey.com",
            "source_url": "https://www.afsa.example/e-f",
        }, "association")

        self.assertEqual(lead.website, "")
        self.assertEqual(lead.domain, "")
        self.assertEqual(lead.email, "info@fostercmgarvey.com")
        self.assertEqual(lead.source_website, "http://info@fostercmgarvey.com")
        self.assertEqual(lead.source, "association")
        self.assertEqual(lead.source_url, "https://www.afsa.example/e-f")
        self.assertEqual(lead.quality_flags, [MALFORMED_WEBSITE_USERINFO])
        self.assertEqual(build_crawl_queue([lead]), [])

    def test_foster_pattern_rejects_malformed_identity_and_preserves_valid_locations(self):
        malformed = adapt_record({
            "company": "Foster and McGarvey Ltd", "website": "http://info@fostercmgarvey.com",
            "address": "4820 Meridian Street", "city": "Edmonton", "province": "AB",
            "phone": "780.463.6666", "email": "info@fostercmgarvey.com",
            "source_url": "https://www.afsa.example/e-f",
        }, "association")
        queue = build_crawl_queue([
            malformed,
            DiscoveryLead(
                company="Foster and McGarvey Funeral Home", website="http://www.fostermcgarvey.com",
                address="9 Muir Drive", city="St. Albert", province="AB",
                phone="780.419.6666", email="info@fostermcgarvey.com",
                source="association", source_url="https://www.afsa.example/s-t",
            ),
            DiscoveryLead(
                company="Foster & McGarvey Downtown", website="https://fostermcgarvey.com/contact",
                address="10011 114 Street", city="Edmonton", province="AB",
                source="manual", source_url="https://fostermcgarvey.com/locations",
            ),
            DiscoveryLead(
                company="Unrelated Funeral Home", website="https://unrelated.example/path",
                address="1 Main Street", city="Calgary", province="AB",
                source="manual", source_url="https://source.example/unrelated",
            ),
        ])

        self.assertEqual([item["domain"] for item in queue], ["fostermcgarvey.com", "unrelated.example"])
        foster = queue[0]
        self.assertEqual(foster["url"], "http://fostermcgarvey.com/")
        self.assertEqual(len(foster["locations"]), 2)
        self.assertEqual(
            {location["address"] for location in foster["locations"]},
            {"9 Muir Drive", "10011 114 Street"},
        )
        self.assertEqual(
            {item["source_url"] for item in foster["provenance"]},
            {"https://www.afsa.example/s-t", "https://fostermcgarvey.com/locations"},
        )
        self.assertNotIn("https://www.afsa.example/e-f", {item["source_url"] for item in foster["provenance"]})
        self.assertEqual(queue, build_crawl_queue([
            malformed,
            DiscoveryLead(
                company="Foster and McGarvey Funeral Home", website="http://www.fostermcgarvey.com",
                address="9 Muir Drive", city="St. Albert", province="AB",
                phone="780.419.6666", email="info@fostermcgarvey.com",
                source="association", source_url="https://www.afsa.example/s-t",
            ),
            DiscoveryLead(
                company="Foster & McGarvey Downtown", website="https://fostermcgarvey.com/contact",
                address="10011 114 Street", city="Edmonton", province="AB",
                source="manual", source_url="https://fostermcgarvey.com/locations",
            ),
            DiscoveryLead(
                company="Unrelated Funeral Home", website="https://unrelated.example/path",
                address="1 Main Street", city="Calgary", province="AB",
                source="manual", source_url="https://source.example/unrelated",
            ),
        ]))

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

    def test_duplicate_location_merge_preserves_complementary_fields_and_sources(self):
        queue = build_crawl_queue([
            DiscoveryLead(company="Example Home", website="example.com", address="1 Main",
                city="Town", province="AB", email="care@example.com",
                source="association", source_url="https://first.example/member"),
            DiscoveryLead(company="Example Home", website="example.com", address="1 Main",
                city="Town", province="AB", contact_name="Jane Smith",
                source="directory", source_url="https://second.example/member"),
        ])
        location = queue[0]["locations"][0]
        self.assertEqual(location["email"], "care@example.com")
        self.assertEqual(location["contact_name"], "Jane Smith")
        self.assertEqual(location["field_sources"]["email"], ["https://first.example/member"])
        self.assertEqual(location["field_sources"]["contact_name"], ["https://second.example/member"])

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
