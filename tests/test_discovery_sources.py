import json
import tempfile
import unittest
from pathlib import Path

from discovery.source_adapters import load_source, parse_source_spec
from discovery_import import import_discovery_sources


class DiscoverySourceTests(unittest.TestCase):

    def test_loads_aliases_from_nested_json_export(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "search.json"
            path.write_text(json.dumps({
                "results": [{
                    "title": "Example Funeral Home",
                    "url": "https://www.example.com/contact",
                    "locality": "Edmonton",
                    "region": "ab",
                    "telephone": "780-555-1234",
                }]
            }), encoding="utf-8")

            leads = load_source(path, "search")

        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0].company, "Example Funeral Home")
        self.assertEqual(leads[0].domain, "example.com")
        self.assertEqual(leads[0].province, "AB")
        self.assertEqual(leads[0].source, "search")

    def test_maps_url_is_provenance_not_business_website(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "maps.json"
            path.write_text(json.dumps([{
                "name": "No Website Funeral Home",
                "url": "https://maps.example/listing/123",
            }]), encoding="utf-8")

            leads = load_source(path, "maps")

        self.assertEqual(leads[0].website, "")
        self.assertEqual(
            leads[0].source_url,
            "https://maps.example/listing/123",
        )

    def test_multi_source_import_deduplicates_and_preserves_provenance(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manual = root / "manual.csv"
            maps = root / "maps.json"
            output = root / "queue.json"
            manual.write_text(
                "company,website,city,province\n"
                "Example Funeral Home,example.com,Edmonton,AB\n",
                encoding="utf-8",
            )
            maps.write_text(json.dumps([{
                "business_name": "Example Funeral Home",
                "website": "https://www.example.com/",
                "listing_url": "https://maps.example/123",
                "phone_number": "780-555-1234",
            }]), encoding="utf-8")

            count = import_discovery_sources(
                [f"manual={manual}", f"maps={maps}"],
                output,
            )
            queue = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(count, 1)
        self.assertEqual(queue[0]["phone"], "780-555-1234")
        self.assertEqual(queue[0]["sources"], ["manual", "maps"])
        self.assertEqual(len(queue[0]["locations"]), 2)
        self.assertEqual(
            {item["source"] for item in queue[0]["provenance"]},
            {"manual", "maps"},
        )

    def test_source_spec_validation(self):
        self.assertEqual(
            parse_source_spec("maps=data/maps.csv"),
            ("maps", Path("data/maps.csv")),
        )
        with self.assertRaisesRegex(ValueError, "TYPE=PATH"):
            parse_source_spec("maps.csv")

    def test_directory_contact_survives_queue_ingestion(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "directory.json"
            output = root / "queue.json"
            source.write_text(json.dumps([{
                "company": "Example Funeral Home", "website": "example.com",
                "contact_name": "Jane Smith", "contact_title": "Member contact",
                "listing_url": "https://directory.example/example",
            }]), encoding="utf-8")
            import_discovery_sources([f"association={source}"], output)
            record = json.loads(output.read_text())[0]

        self.assertEqual(record["contact_name"], "Jane Smith")
        self.assertEqual(record["locations"][0]["contact_name"], "Jane Smith")
        self.assertEqual(record["contact_title"], "Member contact")


if __name__ == "__main__":
    unittest.main()
