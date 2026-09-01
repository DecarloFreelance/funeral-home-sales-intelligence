import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from prepare_legacy_mapping_recheck import prepare


class PrepareLegacyMappingRecheckTests(unittest.TestCase):
    def test_eligible_mapping_becomes_single_candidate(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "mappings.json"
            source.write_text(json.dumps([{
                "directory_record_id": "CFI-0001",
                "company": "Heritage Funeral Centre",
                "city": "Toronto",
                "province": "ON",
                "website": "https://www.heritagefuneralcentre.ca/contact",
                "verification_class": "RECOVERED_VERIFIED",
                "source": "legacy",
            }]))
            summary = prepare(source, root / "out")
            search = json.loads((root / "out/search_results.json").read_text())
            self.assertEqual(summary["eligible_records"], 1)
            self.assertEqual(search[0]["results"][0]["url"], "https://www.heritagefuneralcentre.ca/contact")
            self.assertEqual(summary["network_requests"], 0)

    def test_deceptive_subdomain_is_quarantined_without_fetch(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "mappings.json"
            source.write_text(json.dumps([{
                "directory_record_id": "CFI-0001",
                "company": "Heritage Funeral Centre",
                "city": "Toronto",
                "province": "ON",
                "website": "https://heritagefuneralcentre.ca.getstat.site/",
                "verification_class": "RECOVERED_VERIFIED",
            }]))
            summary = prepare(source, root / "out")
            quarantined = json.loads((root / "out/quarantine.json").read_text())
            self.assertEqual(summary["eligible_records"], 0)
            self.assertEqual(summary["quarantined_records"], 1)
            self.assertEqual(quarantined[0]["identity_domain_label"], "getstat")
            self.assertEqual(quarantined[0]["network_requests"], 0)

    def test_duplicate_ids_fail_closed(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "mappings.json"
            row = {
                "directory_record_id": "CFI-0001", "company": "Heritage Funeral Centre",
                "city": "Toronto", "province": "ON", "website": "https://heritagefuneralcentre.ca/",
            }
            source.write_text(json.dumps([row, row]))
            with self.assertRaisesRegex(ValueError, "duplicate"):
                prepare(source, root / "out")


if __name__ == "__main__":
    unittest.main()
