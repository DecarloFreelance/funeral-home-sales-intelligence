import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from prepare_verified_mapping_crawl import prepare


class PrepareVerifiedMappingCrawlTests(unittest.TestCase):
    def test_deduplicates_domain_and_retains_business_attribution(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            rows = []
            for index, city in ((1, "Toronto"), (2, "Ottawa")):
                rows.append({
                    "directory_record_id": f"CFI-{index:04d}", "directory_index": index,
                    "company": "Heritage Funeral Centre", "city": city, "province": "ON",
                    "website": "https://heritagefuneralcentre.ca/", "domain": "heritagefuneralcentre.ca",
                    "status": "VERIFIED_HIGH", "confidence": "HIGH", "verification_score": .97,
                    "evidence": {"host": "heritagefuneralcentre.ca", "host_overlap": 1},
                })
            source = root / "verified.json"
            source.write_text(json.dumps(rows))
            summary = prepare(source, root / "out")
            queue = json.loads((root / "out/crawl_queue.json").read_text())
            self.assertEqual(summary["crawl_domains"], 1)
            self.assertEqual(summary["verified_mappings"], 2)
            self.assertEqual(queue[0]["directory_record_ids"], ["CFI-0001", "CFI-0002"])
            self.assertTrue(all(url.startswith("https://heritagefuneralcentre.ca/") for url in queue[0]["priority_urls"]))

    def test_current_guard_rejects_deceptive_verified_row(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "verified.json"
            source.write_text(json.dumps([{
                "directory_record_id": "CFI-0001", "company": "Heritage Funeral Centre",
                "city": "Toronto", "province": "ON",
                "website": "https://heritagefuneralcentre.ca.domreaper.com/",
                "status": "VERIFIED_HIGH", "confidence": "HIGH", "verification_score": .97,
                "evidence": {"host": "heritagefuneralcentre.ca.domreaper.com", "host_overlap": 0},
            }]))
            summary = prepare(source, root / "out")
            self.assertEqual(summary["verified_mappings"], 0)
            self.assertEqual(summary["crawl_domains"], 0)


if __name__ == "__main__":
    unittest.main()
